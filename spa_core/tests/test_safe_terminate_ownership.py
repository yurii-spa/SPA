"""Сторож безопасного завершения по доказанной принадлежности (ТЕНЕВОЕ, 22.09).

Авария, воспроизведённая здесь: сессия останавливала СВОЙ невалидный прогон и отбирала
процессы широким совпадением по подстроке командной строки. В выборку попал посторонний
полный прогон CI, который сессия не запускала, — и был убит. Его вывод не писался ни в один
файл, поэтому вердикт не восстановим; принадлежность осталась НЕ ИЗМЕРЕННОЙ навсегда.

Каждый тест ниже — положительный контроль: своя сцена воспроизводит настоящий режим отказа,
а НЕ украшение. Ни один посторонний процесс системы не используется как разрушаемая
фикстура: все подопытные порождены самим тестом.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts' / 'shadow'))

import safe_terminate as ST                # noqa: E402
import claude_run_with_timeout as CRT       # noqa: E402

PY = sys.executable
RUN_ID = f'test-safe-term-{os.getpid()}'
SLEEPER = 'import time,sys;sys.stderr.write("up\\n");sys.stderr.flush();time.sleep(600)'
IGNORER = ('import signal,time,sys\n'
           'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
           'sys.stderr.write("up\\n");sys.stderr.flush()\n'
           'time.sleep(600)\n')


def _spawn(code=SLEEPER, *, run_id=RUN_ID, cwd=None, detach=True):
    env = dict(os.environ)
    if run_id is None:
        env.pop(CRT.RUN_ID_VAR, None)
    else:
        env[CRT.RUN_ID_VAR] = run_id
    p = subprocess.Popen([PY, '-c', code], env=env, cwd=cwd,
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                         start_new_session=detach)
    p.stderr.readline()          # ждём «up»: процесс точно живой и окружение уже exec'нуто
    return p


def _reap(p):
    try:
        p.kill()
    except Exception:             # noqa: BLE001
        pass
    try:
        p.wait(timeout=5)
    except Exception:             # noqa: BLE001
        pass


class Base(unittest.TestCase):
    def setUp(self):
        self.spawned = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for p in self.spawned:
            _reap(p)

    def spawn(self, **kw):
        p = _spawn(**kw)
        self.spawned.append(p)
        return p

    def classify(self, pid, child_pid, **kw):
        return ST.classify(pid, child_pid=child_pid, run_id=RUN_ID,
                           run_age_s=3600.0, **kw)


class OwnedIsOwnedAndForeignIsNot(Base):

    def test_our_own_stamped_child_is_OWNED(self):
        p = self.spawn()
        ev = self.classify(p.pid, p.pid)
        self.assertEqual(ev['state'], ST.OWNED, ev)
        self.assertIn('run_id', ev['instruments'])

    def test_a_child_without_our_stamp_is_NOT_OWNED(self):
        """Отделённый процесс без метки не наш — ни по одному прибору."""
        mine = self.spawn()
        foreign = self.spawn(run_id=None)
        ev = self.classify(foreign.pid, mine.pid)
        self.assertEqual(ev['state'], ST.NOT_OWNED, ev)

    def test_a_process_with_a_DIFFERENT_run_id_is_NOT_OWNED(self):
        mine = self.spawn()
        other = self.spawn(run_id='чужой-прогон-12345')
        ev = self.classify(other.pid, mine.pid)
        self.assertEqual(ev['state'], ST.NOT_OWNED, ev)

    def test_the_same_command_in_another_cwd_is_IDENTITY_MISMATCH(self):
        """Та же команда, другой рабочий каталог — не наш предмет."""
        with TemporaryDirectory() as other:
            p = self.spawn(cwd=other)
            ev = self.classify(p.pid, p.pid, expected_cwd=str(ROOT))
            self.assertIn(ev['state'], (ST.IDENTITY_MISMATCH, ST.OWNERSHIP_UNKNOWN), ev)
            if ev['state'] == ST.IDENTITY_MISMATCH:
                self.assertIn('каталог', ev['reason'])

    def test_the_same_command_in_the_expected_cwd_is_OWNED(self):
        """Обратная сторона: иначе проверка каталога зеленела бы всегда-отказом."""
        p = self.spawn(cwd=str(ROOT))
        ev = self.classify(p.pid, p.pid, expected_cwd=str(ROOT))
        self.assertEqual(ev['state'], ST.OWNED, ev)


class IdentityIsNotJustThePid(Base):

    def test_a_pinned_identity_that_no_longer_matches_is_IDENTITY_MISMATCH(self):
        """Переиспользование номера ОС: тот же pid, другая личность ⇒ не стрелять."""
        p = self.spawn()
        real = self.classify(p.pid, p.pid)['identity']
        forged = (real[0], real[1], real[2], real[3],
                  ST.cmd_fingerprint('совсем другая команда'))
        ev = self.classify(p.pid, p.pid, expected_identity=forged)
        self.assertEqual(ev['state'], ST.IDENTITY_MISMATCH, ev)
        self.assertIn('переиспользовала', ev['reason'])

    def test_the_matching_identity_is_OWNED(self):
        p = self.spawn()
        real = self.classify(p.pid, p.pid)['identity']
        ev = self.classify(p.pid, p.pid, expected_identity=real)
        self.assertEqual(ev['state'], ST.OWNED, ev)

    def test_identity_includes_more_than_the_pid(self):
        self.assertGreater(len(ST.IDENTITY_FIELDS), 1)
        self.assertIn('pid', ST.IDENTITY_FIELDS)
        self.assertIn('cmd_fingerprint', ST.IDENTITY_FIELDS)
        self.assertNotIn('cmd', ST.IDENTITY_FIELDS,
                         'сырая команда в личности = секрет в улике (инв. #7)')


class GoneIsIdempotentSuccess(Base):

    def test_an_already_exited_process_is_PROCESS_GONE(self):
        p = self.spawn()
        pid = p.pid
        _reap(p)
        time.sleep(0.4)
        ev = self.classify(pid, pid)
        self.assertEqual(ev['state'], ST.PROCESS_GONE, ev)

    def test_terminating_a_gone_process_is_a_no_op_success(self):
        p = self.spawn()
        pid = p.pid
        _reap(p)
        time.sleep(0.4)
        ev = ST.safe_terminate(pid, child_pid=pid, run_id=RUN_ID, run_age_s=3600.0,
                               grace_s=1.0)
        self.assertEqual(ev['outcome'], 'ALREADY_GONE')
        self.assertEqual(ev['signals'], [])

    def test_the_call_is_idempotent(self):
        p = self.spawn()
        a = ST.safe_terminate(p.pid, child_pid=p.pid, run_id=RUN_ID, run_age_s=3600.0,
                              grace_s=2.0)
        b = ST.safe_terminate(p.pid, child_pid=p.pid, run_id=RUN_ID, run_age_s=3600.0,
                              grace_s=2.0)
        self.assertTrue(a['terminated'], a)
        self.assertEqual(b['outcome'], 'ALREADY_GONE', b)


class TerminationItself(Base):

    def test_an_owned_process_is_terminated_by_TERM(self):
        p = self.spawn()
        ev = ST.safe_terminate(p.pid, child_pid=p.pid, run_id=RUN_ID, run_age_s=3600.0,
                               grace_s=5.0)
        self.assertEqual(ev['outcome'], 'TERMINATED_BY_TERM', ev)
        self.assertEqual(ev['signals'], ['SIGTERM'])

    def test_a_sigterm_ignoring_owned_process_needs_KILL(self):
        p = self.spawn(code=IGNORER)
        ev = ST.safe_terminate(p.pid, child_pid=p.pid, run_id=RUN_ID, run_age_s=3600.0,
                               grace_s=1.5, poll_s=0.2)
        self.assertEqual(ev['signals'], ['SIGTERM', 'SIGKILL'], ev)
        self.assertEqual(ev['outcome'], 'TERMINATED_BY_KILL', ev)

    def test_the_premise_holds_the_stub_really_ignores_sigterm(self):
        """Без этого предыдущий тест доказывал бы лишь то, что мы дважды стреляли."""
        p = self.spawn(code=IGNORER)
        os.kill(p.pid, signal.SIGTERM)
        time.sleep(0.6)
        self.assertIsNone(p.poll(), 'заглушка НЕ игнорирует SIGTERM — сцена не та')

    def test_a_foreign_process_is_never_signalled(self):
        """Главный тест набора: чужой процесс не получает НИ ОДНОГО сигнала."""
        mine = self.spawn()
        foreign = self.spawn(run_id=None)
        sent = []
        ev = ST.safe_terminate(foreign.pid, child_pid=mine.pid, run_id=RUN_ID,
                               run_age_s=3600.0, grace_s=1.0,
                               sender=lambda pid, sig: sent.append((pid, sig)))
        self.assertEqual(ev['outcome'], 'REFUSED', ev)
        self.assertEqual(sent, [], 'посторонний процесс получил сигнал')
        self.assertIsNone(foreign.poll(), 'посторонний процесс умер')

    def test_identity_change_between_TERM_and_KILL_blocks_the_KILL(self):
        """Личность сменилась между выстрелами ⇒ KILL отменяется, а не «добиваем номер»."""
        p = self.spawn(code=IGNORER)
        real = self.classify(p.pid, p.pid)['identity']
        sent = []
        calls = {'n': 0}
        orig = ST.classify

        def flaky(pid, **kw):
            calls['n'] += 1
            ev = orig(pid, **kw)
            if calls['n'] > 1 and ev['state'] == ST.OWNED:
                # имитируем переиспользование номера: та же перепись, другая личность
                ev = dict(ev, state=ST.IDENTITY_MISMATCH,
                          reason='номер переиспользован (имитация)')
            return ev
        ST.classify = flaky
        try:
            ev = ST.safe_terminate(p.pid, child_pid=p.pid, run_id=RUN_ID,
                                   run_age_s=3600.0, grace_s=1.0, poll_s=0.2,
                                   sender=lambda pid, sig: sent.append(sig))
        finally:
            ST.classify = orig
        self.assertEqual(ev['outcome'], 'KILL_BLOCKED', ev)
        self.assertEqual(sent, [signal.SIGTERM], 'KILL всё-таки был послан')
        self.assertIsNone(p.poll(), 'процесс убит, хотя личность не совпала')


class UnknownOwnershipFailsClosed(Base):

    def test_an_unreadable_process_table_is_OWNERSHIP_UNKNOWN(self):
        p = self.spawn()
        orig = CRT._ps
        CRT._ps = lambda args: (_ for _ in ()).throw(CRT.PsUnavailable('ps не ответил'))
        try:
            ev = self.classify(p.pid, p.pid)
        finally:
            CRT._ps = orig
        self.assertEqual(ev['state'], ST.OWNERSHIP_UNKNOWN, ev)
        self.assertIn('перепись не прочитана', ev['reason'])

    def test_unknown_ownership_never_signals(self):
        p = self.spawn()
        sent = []
        orig = CRT._ps
        CRT._ps = lambda args: (_ for _ in ()).throw(CRT.PsUnavailable('ps не ответил'))
        try:
            ev = ST.safe_terminate(p.pid, child_pid=p.pid, run_id=RUN_ID,
                                   run_age_s=3600.0, grace_s=1.0,
                                   sender=lambda pid, sig: sent.append(sig))
        finally:
            CRT._ps = orig
        self.assertEqual(ev['outcome'], 'REFUSED', ev)
        self.assertEqual(sent, [])
        self.assertIsNone(p.poll())

    def test_only_one_state_permits_termination(self):
        self.assertEqual(ST.MAY_TERMINATE, (ST.OWNED,))


class ANeighbouringPytestSurvives(Base):
    """Прямая проверка аварии: соседний pytest обязан пережить наше завершение."""

    def test_a_neighbouring_pytest_is_not_touched(self):
        with TemporaryDirectory() as td:
            Path(td, 'test_neighbour.py').write_text(
                'import time\ndef test_slow():\n    time.sleep(30)\n', encoding='utf-8')
            env = dict(os.environ)
            env.pop(CRT.RUN_ID_VAR, None)
            # `--rootdir` обязателен: сторож `test_child_pytest_rootdir` требует, чтобы
            # КАЖДЫЙ дочерний прогон был привязан — иначе pytest ищет корень вверх по
            # дереву и может подцепить конфигурацию репозитория. Замер 22.09: без него
            # мой собственный набор дал единственную настоящую регрессию полного CI.
            neigh = subprocess.Popen(
                [PY, '-m', 'pytest', 'test_neighbour.py', '-q', '-p', 'no:randomly',
                 '--rootdir', td],
                cwd=td, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            self.spawned.append(neigh)
            time.sleep(2.0)
            self.assertIsNone(neigh.poll(), 'сосед не поднялся — сцена не та')
            mine = self.spawn()
            sent = []
            ev = ST.safe_terminate(neigh.pid, child_pid=mine.pid, run_id=RUN_ID,
                                   run_age_s=3600.0, grace_s=1.0,
                                   sender=lambda pid, sig: sent.append(sig))
            self.assertEqual(ev['outcome'], 'REFUSED', ev)
            self.assertEqual(sent, [])
            self.assertIsNone(neigh.poll(), 'СОСЕДНИЙ PYTEST УБИТ — авария повторилась')


if __name__ == '__main__':
    unittest.main()


class NoSecretReachesTheEvidence(Base):
    """Инв. #7 в применении к самому прибору: `ps -E` отдаёт ОКРУЖЕНИЕ процесса.

    Замер 22.09: первая редакция этого модуля складывала полную строку `ps -E` в кортеж
    личности, и вывод собственного теста напечатал настоящий PAT из окружения машины.
    Прибор, расследующий принадлежность, не имеет права publish'ить секреты владельца.
    """

    SECRET = 'SPA_TEST_FAKE_SECRET=ghp_ЗАВЕДОМО_ПОДДЕЛЬНЫЙ_0123456789'

    def test_the_command_head_stops_at_the_first_env_pair(self):
        head = ST.cmd_head('python3 -c code ' + self.SECRET + ' PATH=/x')
        self.assertNotIn('ghp_', head)
        self.assertNotIn('SPA_TEST_FAKE_SECRET', head)
        self.assertIn('python3', head)

    def test_the_identity_tuple_carries_a_hash_not_the_command(self):
        p = self.spawn()
        ev = self.classify(p.pid, p.pid)
        ident = ev['identity']
        self.assertEqual(len(ident), len(ST.IDENTITY_FIELDS))
        blob = repr(ident)
        self.assertNotIn('GITHUB', blob)
        self.assertNotIn('ghp_', blob)
        self.assertNotIn('TOKEN', blob)
        self.assertNotIn('PATH=', blob)

    def test_no_env_pair_survives_anywhere_in_the_evidence(self):
        """Меряем ВСЮ улику, а не только то поле, о котором помним."""
        import json as _json
        p = self.spawn()
        ev = self.classify(p.pid, p.pid)
        blob = _json.dumps(ev, ensure_ascii=False, default=str)
        self.assertNotIn('ghp_', blob)
        self.assertNotIn('github_pat', blob)
        self.assertIsNone(ST._ENV_PAIR.search(blob),
                          'в улике осталась пара KEY=VALUE из окружения')

    def test_the_fingerprint_still_distinguishes_two_commands(self):
        """Обратная сторона: хеш обязан различать, иначе он не личность."""
        a = ST.cmd_fingerprint('python3 -c один')
        b = ST.cmd_fingerprint('python3 -c другой')
        self.assertNotEqual(a, b)
        self.assertEqual(a, ST.cmd_fingerprint('python3 -c один'))
