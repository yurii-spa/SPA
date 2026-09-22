#!/usr/bin/env python3
"""Безопасное завершение процесса по ДОКАЗАННОЙ принадлежности (ТЕНЕВОЕ, не проведено).

Почему это НЕ новая архитектура
===============================
Модель принадлежности в репозитории УЖЕ ЕСТЬ и она измерена глубже, чем заново написанная:
``scripts/claude_run_with_timeout.py`` (решение ARB 18.09) доказывает владение объединением
ЧЕТЫРЁХ приборов — ``tree`` (обход по ``ppid``), ``group`` (``pgid``), ``session`` (``sid``)
и ``run_id`` (метка ``SPA_RUN_ID`` в окружении) — и называет вслух измеренную слепоту
``run_id``: ``ps -E`` не отдаёт окружение платформенных бинарей macOS (``bash`` нет,
``python`` да, ``git`` НЕ ИЗМЕРЕНО). Её охраняют ~25 тестов, включая положительный контроль
«отключи ``run_id`` — отделившийся потомок остаётся жив».

Поэтому здесь НЕ дублируется ни один прибор: перепись импортируется. Модуль добавляет ровно
то, чего в ней нет, и ни строкой больше.

Что добавлено и почему именно это
=================================
1. **Явные состояния принадлежности.** ``census`` отвечает списком владеемых; вопрос
   «а этот конкретный pid — мой?» имел ответ «его нет в списке», и это сливало три разных
   исхода в один: чужой процесс, неизвестная принадлежность (``ps`` не прочитан) и уже
   вышедший процесс. Смешать их — значит когда-нибудь выстрелить по неизвестному.

2. **Сверка КОРТЕЖА личности, а не только pid.** ``_terminate`` перед выстрелом сверяет
   ``o.pid in still`` — то есть «pid снова в переписи». Между TERM и KILL номер может быть
   переиспользован ОС, и если новый владелец номера тоже наш, прежняя проверка выстрелит по
   НЕ ТОМУ нашему процессу. Требование ARB строже: «та же самая владеемая личность».
   Здесь сверяются ``(pid, ppid, pgid, sid, cmd)``.

3. **Идемпотентность.** Повторный вызов на вышедшем процессе — успех-no-op, а не ошибка.

Почему у него есть CLI
======================
Замер 22.09: небезопасным актором оказался НЕ код, а сессия, действовавшая через оболочку —
``kill`` по списку ``pgrep -f pytest``. В проде настоящих точек завершения три, и все три
безопасны; у оболочки же примитива не было вовсе, поэтому импровизация была единственным
способом. CLI закрывает именно это.

НЕ ПРОВЕДЕНО в живые расписания. LLM запрещён. Только stdlib.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# Перепись живёт в `scripts/`, а модуль — в `scripts/shadow/`: теневой код не является
# запускаемым скриптом launchd и потому не входит в население храповика (см. README).
for _p in (_HERE, _HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import claude_run_with_timeout as CRT       # noqa: E402  — перепись НЕ дублируется

#: Состояния принадлежности. Три из пяти — разные причины НЕ стрелять, и они обязаны быть
#: различимы: слить их значило бы когда-нибудь выстрелить по неизвестному (инв. #17).
OWNED = 'OWNED'
NOT_OWNED = 'NOT_OWNED'
OWNERSHIP_UNKNOWN = 'OWNERSHIP_UNKNOWN'
PROCESS_GONE = 'PROCESS_GONE'
IDENTITY_MISMATCH = 'IDENTITY_MISMATCH'

#: Стрелять разрешено ровно в одном состоянии. Список существует ради теста: он превращает
#: «мы вроде не стреляем в чужих» в проверяемое утверждение.
MAY_TERMINATE = (OWNED,)

IDENTITY_FIELDS = ('pid', 'ppid', 'pgid', 'sid', 'cmd_fingerprint')

#: Сколько символов команды попадает в отпечаток. `ps -E` отдаёт КОМАНДУ ВМЕСТЕ С
#: ОКРУЖЕНИЕМ, и в окружении этой машины лежат секреты (замер 22.09: собственный вывод
#: теста напечатал настоящий PAT, потому что полная строка попала в улику). Инвариант #7
#: запрещает секреты в файлах, поэтому здесь: (а) в отпечаток идёт ХЕШ, не текст;
#: (б) человекочитаемый остаток обрезается до головы строки, до первого `KEY=VALUE`.
CMD_HEAD_CHARS = 90

_ENV_PAIR = re.compile(r'\s[A-Z_][A-Z0-9_]*=')


def cmd_head(cmd: str) -> str:
    """Голова командной строки БЕЗ окружения. Секрет здесь появиться не может."""
    text = cmd or ''
    m = _ENV_PAIR.search(text)
    if m:
        text = text[:m.start()]
    return text[:CMD_HEAD_CHARS]


def cmd_fingerprint(cmd: str) -> str:
    """Отпечаток команды. ХЕШ, а не текст: сравнивать можно, прочитать секрет нельзя."""
    return hashlib.sha256((cmd or '').encode('utf-8', errors='replace')).hexdigest()[:16]


def identity(owned) -> tuple:
    """Кортеж личности. Номер процесса ОДИН не является личностью: ОС его переиспользует.

    В кортеж входит ОТПЕЧАТОК команды, а не команда: полная строка `ps -E` несёт
    окружение процесса, то есть потенциально секреты.
    """
    return (owned.pid, owned.ppid, owned.pgid, owned.sid,
            cmd_fingerprint(owned.cmd))


def _alive(pid: int) -> bool:
    """Жив ли процесс. ЗОМБИ — НЕ жив.

    Замер 22.09: `os.kill(pid, 0)` на зомби УСПЕШЕН — номер ещё занят записью в таблице,
    пока родитель не пожал потомка. Из-за этого убитый ребёнок читался как выживший, и
    примитив уходил в ветку KILL на уже мёртвом процессе. Существующая перепись
    `claude_run_with_timeout` зомби исключает («зомби с нашей меткой — не выживший»),
    поэтому состояние спрашивается у `ps`, а сигнал 0 остаётся лишь быстрым отсевом.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # существует, но чужой — это НЕ «мёртв»
    try:
        table = CRT._ps(['-o', 'stat=', '-p', str(pid)])
    except CRT.PsUnavailable:
        return True          # не измерено ⇒ считаем живым: fail-CLOSED, не стреляем
    stat = table.strip()
    if not stat:
        return False
    return not stat.startswith('Z')


def classify(pid: int, *, child_pid: int, run_id: str, run_age_s: float,
             expected_identity=None, expected_cwd=None, self_pid=None,
             self_sid=None, instruments=None):
    """Состояние ОДНОГО номера процесса. Ответ — состояние и улика, никогда не догадка."""
    self_pid = os.getpid() if self_pid is None else self_pid
    if self_sid is None:
        self_sid = CRT._safe_sid(self_pid)
    ev = {'pid': pid, 'run_id': run_id, 'checked_at': CRT._ts()}
    try:
        owned_rows = CRT.census(child_pid, run_id, run_age_s, self_pid=self_pid,
                                self_sid=self_sid, instruments=instruments)
    except CRT.PsUnavailable as exc:
        # Прибор не ответил ⇒ принадлежность НЕ ИЗМЕРЕНА. Не «чужой» и не «мой».
        ev.update(state=OWNERSHIP_UNKNOWN, reason=f'перепись не прочитана: {exc}')
        return ev
    rows = {o.pid: o for o in owned_rows}
    row = rows.get(pid)
    if row is None:
        if not _alive(pid):
            ev.update(state=PROCESS_GONE, reason='процесса нет')
            return ev
        ev.update(state=NOT_OWNED, reason='жив, но в переписи владения не значится')
        return ev
    ev['identity'] = identity(row)
    ev['cmd_head'] = cmd_head(row.cmd)      # голова БЕЗ окружения: секрета тут нет
    ev['instruments'] = sorted(row.by)
    if expected_identity is not None and tuple(expected_identity) != identity(row):
        ev.update(state=IDENTITY_MISMATCH,
                  reason='номер тот же, личность другая — ОС переиспользовала pid',
                  expected_identity=tuple(expected_identity))
        return ev
    if expected_cwd is not None:
        cwd = process_cwd(pid)
        ev['cwd'] = cwd
        if cwd is None:
            ev.update(state=OWNERSHIP_UNKNOWN,
                      reason='рабочий каталог не прочитан — сверить с ожидаемым нечем')
            return ev
        if os.path.realpath(cwd) != os.path.realpath(expected_cwd):
            ev.update(state=IDENTITY_MISMATCH,
                      reason=f'рабочий каталог {cwd!r} ≠ ожидаемого {expected_cwd!r}')
            return ev
    ev.update(state=OWNED, reason=None)
    return ev


def process_cwd(pid: int):
    """Рабочий каталог процесса. Не прочитан ⇒ ``None`` (третий исход), не пустая строка."""
    try:
        import subprocess
        p = subprocess.run(['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'],
                           capture_output=True, text=True, timeout=20)
    except (OSError, Exception):        # noqa: BLE001 — таймаут тоже «не прочитан»
        return None
    if p.returncode != 0:
        return None
    for line in p.stdout.splitlines():
        if line.startswith('n'):
            return line[1:]
    return None


def safe_terminate(pid: int, *, child_pid: int, run_id: str, run_age_s: float,
                   expected_identity=None, expected_cwd=None, grace_s: float = 5.0,
                   poll_s: float = 0.25, now=time.monotonic, instruments=None,
                   sender=None):
    """TERM → ожидание → KILL, и КАЖДЫЙ выстрел — только по подтверждённой личности.

    Возвращает улику: состояние до, посланные сигналы, состояние после, исход.
    Неизвестная принадлежность, чужой процесс и несовпадение личности — **отказ**,
    fail-CLOSED. Вышедший процесс — идемпотентный успех.
    """
    send = sender or CRT._signal_pid
    ev = {'pid': pid, 'run_id': run_id, 'signals': [], 'refusals': []}
    before = classify(pid, child_pid=child_pid, run_id=run_id, run_age_s=run_age_s,
                      expected_identity=expected_identity, expected_cwd=expected_cwd,
                      instruments=instruments)
    ev['before'] = before
    if before['state'] == PROCESS_GONE:
        ev.update(outcome='ALREADY_GONE', terminated=False)
        return ev
    if before['state'] not in MAY_TERMINATE:
        ev['refusals'].append(before['state'])
        ev.update(outcome='REFUSED', terminated=False, reason=before['reason'])
        return ev
    pinned = before['identity']          # личность, по которой только и разрешено стрелять

    send(pid, signal.SIGTERM)
    ev['signals'].append('SIGTERM')
    deadline = now() + grace_s
    while now() < deadline:
        time.sleep(poll_s)
        if not _alive(pid):
            ev.update(outcome='TERMINATED_BY_TERM', terminated=True)
            ev['after'] = {'state': PROCESS_GONE}
            return ev
    # Перед KILL личность перепроверяется ЗАНОВО: между выстрелами номер мог быть
    # переиспользован, и «pid снова в переписи» этого не различает.
    again = classify(pid, child_pid=child_pid, run_id=run_id, run_age_s=run_age_s,
                     expected_identity=pinned, expected_cwd=expected_cwd,
                     instruments=instruments)
    ev['after_grace'] = again
    if again['state'] == PROCESS_GONE:
        ev.update(outcome='ALREADY_GONE', terminated=False)
        return ev
    if again['state'] not in MAY_TERMINATE:
        ev['refusals'].append(again['state'])
        ev.update(outcome='KILL_BLOCKED', terminated=False, reason=again['reason'])
        return ev
    send(pid, signal.SIGKILL)
    ev['signals'].append('SIGKILL')
    time.sleep(poll_s)
    ev['after'] = {'state': PROCESS_GONE if not _alive(pid) else 'STILL_ALIVE'}
    ev.update(outcome='TERMINATED_BY_KILL' if not _alive(pid) else 'SURVIVED_KILL',
              terminated=not _alive(pid))
    return ev


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pid', type=int, required=True)
    ap.add_argument('--child-pid', type=int, required=True,
                    help='наш собственный порождённый процесс — корень дерева владения')
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--run-age-s', type=float, required=True)
    ap.add_argument('--expected-cwd')
    ap.add_argument('--grace-s', type=float, default=5.0)
    ap.add_argument('--classify-only', action='store_true')
    ap.add_argument('--json')
    ns = ap.parse_args(argv)
    if ns.classify_only:
        ev = classify(ns.pid, child_pid=ns.child_pid, run_id=ns.run_id,
                      run_age_s=ns.run_age_s, expected_cwd=ns.expected_cwd)
        state = ev['state']
    else:
        ev = safe_terminate(ns.pid, child_pid=ns.child_pid, run_id=ns.run_id,
                            run_age_s=ns.run_age_s, expected_cwd=ns.expected_cwd,
                            grace_s=ns.grace_s)
        state = ev['outcome']
    print(json.dumps(ev, ensure_ascii=False, indent=1, default=str))
    if ns.json:
        Path(ns.json).write_text(json.dumps(ev, ensure_ascii=False, indent=1, default=str),
                                 encoding='utf-8')
    return 0 if state in ('OWNED', 'TERMINATED_BY_TERM', 'TERMINATED_BY_KILL',
                          'ALREADY_GONE') else 2


if __name__ == '__main__':
    raise SystemExit(main())
