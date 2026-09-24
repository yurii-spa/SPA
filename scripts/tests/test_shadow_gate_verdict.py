#!/usr/bin/env python3
"""Сторож вердикта теневого гейта доставки (``scripts/bridge_shadow/shadow_gate.py``).

Авария, которую воспроизводит набор (замер цикла #690 на живом коде, заказ G83 п. 3 —
пятый заказ подряд, числивший это остатком). Прежний вердикт читал счётчик классов
ДВУМЯ именованными ключами::

    'CLEAN' if not counts.get(UNEXPLAINED) and not counts.get(WEAKENING) else 'DIRTY'

а ``classify_mismatch`` умеет вернуть третий класс — ``OLD_DECISION_NOT_RECORDED``.
Обе сцены ниже измерены ДО починки и обе давали ``CLEAN`` с кодом возврата 0:

==================================  ========  ==================================
сцена                               событий   вердикт ДО починки
==================================  ========  ==================================
базы моста нет на объявленном пути         0  CLEAN (и ``read_production_events``
                                              возвращал ``[]`` — «нет базы» было
                                              неотличимо от «база пуста»)
база есть, сравнимых событий ноль          6  CLEAN при
                                              ``{OLD_DECISION_NOT_RECORDED: 6}``
==================================  ========  ==================================

Цена этого выше обычной ошибки: весь смысл теневого прогона — доказать, что новый
гейт НИКОГДА не ослабляет старый. «Ослаблений 0» на нуле сравнений — подделка
доказательства безопасности, и от настоящего она неотличима.

Контроли идут В ОБЕ СТОРОНЫ. Проверка, которая только краснеет на прежнем поведении,
не отличима от проверки, закрасившей всё подряд: сцены 8–9 требуют, чтобы настоящее
сравнение без вреда осталось ``CLEAN``, а настоящий вред — ``DIRTY``.

Прототип моста (``~/studio-os-scratch``) подменяется объявленной заглушкой, а не
обходится пропуском: тест, который в CI превращается в ``skipped``, молча снимает
сторожа — «не измерено» становится неотличимо от «прошло»
(``.claude/rules/deployment.md``). С заглушкой набор меряет ОДНО И ТО ЖЕ на машине
владельца и в CI.

Только stdlib. Ничего не пишет в боевые каталоги.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_GATE_DIR = _REPO / 'scripts' / 'bridge_shadow'


def _install_prototype_stub():
    """Объявленная заглушка границы с прототипом моста.

    Ставится ДО загрузки ``shadow_gate`` и поэтому действует одинаково там, где
    прототип есть, и там, где его нет. Это ровно тот приём, которым набор адаптеров
    подменяет живой фид (``FakeFeed``): граница объявлена, а не подсмотрена.
    """
    PASSED, FAILED = 'PASSED', 'FAILED'
    PRE, POST = 'PRE_COMMIT', 'POST_COMMIT'

    class TestVerdict:
        def __init__(self, verdict, phase, exit_code=0, reason=''):
            self.verdict, self.phase = verdict, phase
            self.exit_code, self.reason = exit_code, reason

    class CanonicalTarget:
        def __init__(self, name, repo_root):
            self.name, self.repo_root = name, repo_root

    class DeliveryFacts:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def classify_test_run(*, exit_code, timed_out, output, phase):
        return TestVerdict(PASSED if exit_code == 0 else FAILED, phase, exit_code)

    def evaluate_delivery_gate(facts):
        """Решение гейта задаётся сценой через ``task_id``, а не угадывается."""
        if str(getattr(facts, 'task_id', '')).startswith('ALLOW'):
            return True, []
        return False, ['улики не хватает']

    di = types.ModuleType('bridge.delivery_integrity')
    for name, val in dict(
            PASSED=PASSED, FAILED=FAILED, PHASE_PRE_COMMIT=PRE, PHASE_POST_COMMIT=POST,
            TestVerdict=TestVerdict, CanonicalTarget=CanonicalTarget,
            DeliveryFacts=DeliveryFacts, classify_test_run=classify_test_run,
            evaluate_delivery_gate=evaluate_delivery_gate).items():
        setattr(di, name, val)
    pkg = types.ModuleType('bridge')
    pkg.delivery_integrity = di
    sys.modules['bridge'] = pkg
    sys.modules['bridge.delivery_integrity'] = di
    return di


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


DI = _install_prototype_stub()
SV = _load('shadow_verdict', 'scripts/bridge_shadow/shadow_verdict.py')
SG = _load('shadow_gate', 'scripts/bridge_shadow/shadow_gate.py')


def _bridge_db(root, tasks):
    """База моста со спутниками. ``tasks`` — список ``(task_id, status)``."""
    db = Path(root) / 'bridge.db'
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE tasks (task_id TEXT, run_id TEXT, status TEXT, '
                 'tree_hash_before TEXT)')
    conn.execute('CREATE TABLE turns (task_id TEXT, phase TEXT, status TEXT)')
    conn.execute('CREATE TABLE gates (task_id TEXT, status TEXT)')
    for tid, status in tasks:
        conn.execute('INSERT INTO tasks VALUES (?,?,?,?)',
                     (tid, f'run-{tid}', status, 'tree-before'))
    conn.commit()
    conn.close()
    return db


class VerdictIsThreeValued(unittest.TestCase):
    """Правило вердикта. Каждая сцена — измеренная авария либо контроль к ней."""

    def test_six_incomparable_events_are_NOT_clean(self):
        # Сцена 2 замера: ДО починки — CLEAN на нуле сравнений.
        v, why = SV.shadow_verdict({SV.OLD_DECISION_NOT_RECORDED: 6},
                                   events=6, source_read=True)
        self.assertEqual(v, SV.UNMEASURED, why)
        self.assertIn('сравнения не состоялось', why)

    def test_zero_events_from_a_read_source_are_NOT_clean(self):
        v, why = SV.shadow_verdict({}, events=0, source_read=True)
        self.assertEqual(v, SV.UNMEASURED, why)

    def test_an_unread_source_is_NOT_clean(self):
        # Сцена 1 замера: базы нет — ДО починки CLEAN с кодом 0.
        v, why = SV.shadow_verdict({}, events=0, source_read=False)
        self.assertEqual(v, SV.UNMEASURED, why)
        self.assertIn('не прочитан', why)

    def test_a_future_class_does_not_pass_in_silence(self):
        """Глубина дефекта: вердикт спрашивал про ДВА ИМЕНИ, а не про перечень.

        Поэтому молча проходил бы и класс, которого сегодня ещё нет, — не только
        сегодняшний ``OLD_DECISION_NOT_RECORDED``.
        """
        v, why = SV.shadow_verdict({'CLASS_ADDED_NEXT_YEAR': 3},
                                   events=3, source_read=True)
        self.assertEqual(v, SV.UNMEASURED, why)
        self.assertIn('CLASS_ADDED_NEXT_YEAR', why)

    def test_a_measured_weakening_is_not_drowned_by_unmeasured_neighbours(self):
        """Порядок ветвей выбран: вред объявляется ПЕРВЫМ.

        Пять несравнимых событий рядом с одним настоящим ослаблением не имеют права
        превратить находку в «не измерено» — иначе починка потеряла бы ровно то,
        ради чего теневой прогон затеян.
        """
        v, why = SV.shadow_verdict({SV.WEAKENING: 1, SV.OLD_DECISION_NOT_RECORDED: 5},
                                   events=6, source_read=True)
        self.assertEqual(v, SV.DIRTY, why)
        self.assertIn('WEAKENING', why)

    def test_an_unknown_class_beside_harm_is_still_named(self):
        """Вред побеждает, но незнакомый класс не исчезает из причины."""
        v, why = SV.shadow_verdict({SV.WEAKENING: 1, 'STRANGER': 2},
                                   events=3, source_read=True)
        self.assertEqual(v, SV.DIRTY, why)
        self.assertIn('STRANGER', why)

    def test_unexplained_is_harm_too(self):
        v, _ = SV.shadow_verdict({SV.UNEXPLAINED: 1, SV.AGREE: 1},
                                 events=2, source_read=True)
        self.assertEqual(v, SV.DIRTY)

    def test_a_real_comparison_without_harm_stays_CLEAN(self):
        """Контроль в ОБРАТНУЮ сторону: починка не красит всё подряд."""
        v, why = SV.shadow_verdict({SV.AGREE: 4, SV.EXPLAINED_STRICTER: 2},
                                   events=6, source_read=True)
        self.assertEqual(v, SV.CLEAN, why)

    def test_partial_coverage_is_CLEAN_but_the_gap_is_NAMED(self):
        """Сравнили часть — вердикт чист по ней, но покрытие видно, а не молчит."""
        v, why = SV.shadow_verdict({SV.AGREE: 1, SV.OLD_DECISION_NOT_RECORDED: 9},
                                   events=10, source_read=True)
        self.assertEqual(v, SV.CLEAN, why)
        self.assertIn('9', why)

    def test_every_outcome_carries_a_reason(self):
        """Вердикт без причины нечем поверить, а у «не измерено» причина и есть
        указание, что чинить."""
        for counts, events, read in (({SV.AGREE: 1}, 1, True),
                                     ({SV.WEAKENING: 1}, 1, True),
                                     ({}, 0, False),
                                     ({}, 0, True),
                                     ({'X': 1}, 1, True)):
            v, why = SV.shadow_verdict(counts, events=events, source_read=read)
            self.assertTrue(why and why.strip(), (v, counts))

    def test_the_three_outcomes_have_three_distinct_exit_codes(self):
        codes = {SV.EXIT_CODE[v] for v in (SV.CLEAN, SV.DIRTY, SV.UNMEASURED)}
        self.assertEqual(codes, {0, 1, 2})
        self.assertEqual(SV.EXIT_CODE[SV.CLEAN], 0)
        self.assertEqual(SV.EXIT_CODE[SV.UNMEASURED], 2)


class TheClassListIsClosed(unittest.TestCase):

    def test_not_recorded_is_a_declared_constant_not_a_bare_literal(self):
        """Регрессия: класс возвращался строковым литералом прямо из функции и
        потому отсутствовал в перечне «виды расхождения» — его нечем было учесть."""
        self.assertIn(SV.OLD_DECISION_NOT_RECORDED, SV.MISMATCH_CLASSES)
        src = (_GATE_DIR / 'shadow_verdict.py').read_text(encoding='utf-8')
        self.assertIn("OLD_DECISION_NOT_RECORDED = 'OLD_DECISION_NOT_RECORDED'", src)

    def test_classify_mismatch_never_leaves_the_declared_list(self):
        seen = set()
        for old in (SV.OLD_ALLOWED, SV.OLD_BLOCKED, SV.OLD_UNKNOWN, 'СОВСЕМ_ДРУГОЕ'):
            for shadow in (SV.WOULD_ALLOW, SV.WOULD_BLOCK, 'ТРЕТЬЕ'):
                for why in ([], ['причина'], ['все условия доставки выполнены']):
                    seen.add(SV.classify_mismatch(old, shadow, why))
        self.assertTrue(seen <= set(SV.MISMATCH_CLASSES), seen - set(SV.MISMATCH_CLASSES))
        self.assertIn(SV.OLD_DECISION_NOT_RECORDED, seen)

    def test_compared_and_not_compared_partition_the_list(self):
        self.assertEqual(set(SV.COMPARED) | set(SV.NOT_COMPARED),
                         set(SV.MISMATCH_CLASSES))
        self.assertEqual(set(SV.COMPARED) & set(SV.NOT_COMPARED), set())

    def test_harm_is_a_subset_of_comparisons(self):
        """Вред может быть найден только там, где сравнение СОСТОЯЛОСЬ."""
        self.assertTrue(set(SV.HARM) <= set(SV.COMPARED))

    def test_the_gate_holds_ONE_copy_of_the_rule(self):
        """Правило и его вторая копия — тот же класс дефекта, что чинит весь ряд."""
        self.assertIs(SG.classify_mismatch, SV.classify_mismatch)
        self.assertIs(SG.shadow_verdict, SV.shadow_verdict)
        gate_src = (_GATE_DIR / 'shadow_gate.py').read_text(encoding='utf-8')
        self.assertNotIn('def classify_mismatch', gate_src)


class TheSourceRefusesOutLoud(unittest.TestCase):

    def test_a_missing_bridge_db_refuses_instead_of_returning_empty(self):
        """«Базы нет» и «база пуста» — разные утверждения; ДО починки оба были ``[]``."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SV.SourceNotRead):
                SG.read_production_events(db_path=Path(tmp) / 'nope.db',
                                          artifacts_root=Path(tmp) / 'art')

    def test_an_existing_empty_db_is_read_and_stays_empty(self):
        """Контроль в обратную сторону: прочитанная пустая база — НЕ отказ чтения."""
        with tempfile.TemporaryDirectory() as tmp:
            db = _bridge_db(tmp, [])
            self.assertEqual(
                SG.read_production_events(db_path=db, artifacts_root=Path(tmp) / 'art'),
                [])


class TheRunEndToEnd(unittest.TestCase):

    def _run(self, tasks, tmp, db=None):
        target = DI.CanonicalTarget(name='canon', repo_root=tmp)
        return SG.run_shadow(db_path=db or _bridge_db(tmp, tasks),
                             artifacts_root=Path(tmp) / 'art', target=target)

    def test_a_missing_db_yields_UNMEASURED_and_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._run([], tmp, db=Path(tmp) / 'nope.db')
            self.assertEqual(out['verdict'], SV.UNMEASURED, out)
            self.assertFalse(out['source_read'])
            self.assertEqual(SV.EXIT_CODE[out['verdict']], 2)

    def test_only_incomparable_events_yield_UNMEASURED_and_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._run([(f'T{i}', 'running') for i in range(6)], tmp)
            self.assertEqual(out['events'], 6)
            self.assertEqual(out['by_mismatch'],
                             {SV.OLD_DECISION_NOT_RECORDED: 6})
            self.assertEqual(out['verdict'], SV.UNMEASURED, out)
            self.assertEqual(SV.EXIT_CODE[out['verdict']], 2)

    def test_a_real_weakening_yields_DIRTY_and_exit_one(self):
        """Старый путь закрыл, заглушка гейта пускает — ослабление, недопустимое
        ни в одном случае."""
        with tempfile.TemporaryDirectory() as tmp:
            out = self._run([('ALLOW-1', 'failed')], tmp)
            self.assertEqual(out['by_mismatch'], {SV.WEAKENING: 1}, out)
            self.assertEqual(out['verdict'], SV.DIRTY, out)
            self.assertEqual(out['weakening'], ['ALLOW-1'])
            self.assertEqual(SV.EXIT_CODE[out['verdict']], 1)

    def test_a_real_agreement_yields_CLEAN_and_exit_zero(self):
        """Контроль в обратную сторону на полном контуре."""
        with tempfile.TemporaryDirectory() as tmp:
            out = self._run([('BLOCK-1', 'failed')], tmp)
            self.assertEqual(out['by_mismatch'], {SV.AGREE: 1}, out)
            self.assertEqual(out['verdict'], SV.CLEAN, out)
            self.assertEqual(SV.EXIT_CODE[out['verdict']], 0)

    def test_the_document_carries_coverage_not_just_a_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._run([('BLOCK-1', 'failed'), ('T2', 'running')], tmp)
            self.assertEqual(out['compared'], 1, out)
            self.assertEqual(out['not_compared'], 1, out)
            self.assertEqual(out['unknown_classes'], [])
            self.assertTrue(out['why_verdict'].strip())

    def test_main_returns_two_when_nothing_was_compared(self):
        """Код возврата — то, что читает вызывающий; ДО починки он был 0."""
        with tempfile.TemporaryDirectory() as tmp:
            # База кладётся ТУДА, ГДЕ её ищет ``main`` (``<root>/state/bridge.db``):
            # иначе сцена молча мерила бы «базы нет», а не «сравнивать не с чем»,
            # и была бы зелёной на своём вопросе вместо нужного.
            state = Path(tmp) / 'state'
            state.mkdir()
            _bridge_db(state, [(f'T{i}', 'running') for i in range(3)])
            out = Path(tmp) / 'out.json'
            code = SG.main(['--bridge-root', tmp, '--target-repo', tmp,
                            '--json', str(out)])
            self.assertEqual(code, 2)
            doc = json.loads(out.read_text(encoding='utf-8'))
            self.assertTrue(doc['source_read'], doc)          # база ПРОЧИТАНА
            self.assertEqual(doc['events'], 3, doc)           # события есть
            self.assertEqual(doc['compared'], 0, doc)         # сравнений ноль

    def test_main_returns_zero_only_on_a_real_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'
            state.mkdir()
            _bridge_db(state, [('BLOCK-1', 'failed')])
            code = SG.main(['--bridge-root', tmp, '--target-repo', tmp])
            self.assertEqual(code, 0)


if __name__ == '__main__':
    unittest.main()
