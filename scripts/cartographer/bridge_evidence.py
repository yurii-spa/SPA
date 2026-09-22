#!/usr/bin/env python3
"""Director OS v1.3 · Улики моста — ПРОИЗВОДНАЯ проекция, без вбитых чисел.

Что здесь меняется
==================
v1.2 получала состояние моста ПАРАМЕТРОМ: «11 задач, 11 прогонов, 29 ходов, 5 гейтов».
Числа были верны в день замера и переставали быть верными молча. Здесь их не вбивают —
их читают.

Главная поправка к собственному разбору
=======================================
В красной команде я написал: «мост дважды дошёл до канонической доставки». Утверждение
верно по факту, но **база данных его не доказывает**. В схеме нет колонок ни под
идентификатор коммита, ни под репозиторий: самая дальняя стадия, доказуемая средствами
БД, — одобрение владельцем. Коммиты существуют, и доказывает их другая улика — файл
``artifacts/<run_id>/apply/manifest.json`` на диске, где лежат ``apply_commit`` и
``task_id``. Поэтому проекция читает ДВА носителя и держит их порознь: что доказано
базой и что доказано каталогом прогона. Сложить их в одно число значило бы снова выдать
улику одного носителя за улику другого.

Read-only и на КОПИИ
====================
Боевая база не открывается вовсе. Копируются сам файл и его спутники ``-wal``/``-shm`` —
без ``-wal`` прочиталась бы база многонедельной давности, потому что свежие записи живут
в журнале. Копия открывается в режиме только для чтения.

Личность владельца
==================
``gates.decided_by`` и ``apply/manifest.json:confirmed_by`` содержат идентификатор
владельца. Он НЕ попадает в проекцию ни в каком виде: наружу уходит только признак
«решение подтверждено» и имя колонки. Это граница, а не настройка.

Только stdlib. Ничего не пишет в боевые каталоги.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DOMAIN = 'BUILD'

#: Цепочка сквозного пути. Каждая стадия обязана иметь СВОЙ носитель улики.
STAGES = ('CREATED', 'INTAKE', 'PLANNED', 'EXECUTED', 'REVIEWED',
          'OWNER_GATE', 'OUTPUT', 'COMMIT', 'CANONICAL_DELIVERY')

#: Колонки, которые не выходят наружу никогда. Список существует ради теста.
IDENTITY_COLUMNS = ('decided_by', 'session_id', 'thread_id', 'input_path',
                    'output_path', 'bundle_path', 'error', 'signature', 'value',
                    'confirmed_by')

#: Разрывы контракта улик, найденные замером. Классификация — с указанием писателя.
CONTRACT_GAPS = (
    {'anomaly': 'таблица artifacts пуста при завершённых задачах',
     'classification': 'WRITER GAP',
     'evidence_note': 'писатель существует и вызывается адаптерами, но боевая сборка '
                 'сохраняет артефакты своим путём в файл и в manifest.json, минуя БД; '
                 'на диске сотни объектов, в таблице ноль'},
    {'anomaly': 'evidence_hash пуст',
     'classification': 'SCHEMA GAP',
     'evidence_note': 'имя встречается только в определении схемы и в тестах, повторяющих '
                 'его; ни один INSERT и ни один UPDATE колонку не трогает — писателя '
                 'не существует'},
    {'anomaly': 'tree_hash_before / tree_hash_after пусты',
     'classification': 'SCHEMA GAP',
     'evidence_note': 'величина вычисляется и участвует в решении о применении диффа, но в '
                 'колонки не записывается: решение принимается по значению, которого '
                 'потом нет в улике'},
    {'anomaly': 'requires_owner_approval = 0 при существующих гейтах',
     'classification': 'SCHEMA GAP',
     'evidence_note': 'поле мёртвое: только определение схемы и тесты. Ноль здесь — значение '
                 'по умолчанию, то есть «не измерено», выданное за «не требуется». '
                 'Решение о гейте живёт в отдельной таблице и признака задачи не касается'},
)


def _now():
    return datetime.now(timezone.utc)


def snapshot_database(db_path, workdir):
    """Копия базы вместе со спутниками. Боевой файл после этого не открывается."""
    src = Path(db_path)
    if not src.exists():
        return None
    dst = Path(workdir) / src.name
    shutil.copy2(src, dst)
    for suffix in ('-wal', '-shm'):
        side = src.with_name(src.name + suffix)
        if side.exists():
            shutil.copy2(side, dst.with_name(dst.name + suffix))
    return dst


def _tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [r[0] for r in rows]


def _columns(conn, table):
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def read_database(db_path):
    """Всё, что база действительно знает. Отсутствие базы — ``None``, а не пустота."""
    work = tempfile.mkdtemp(prefix='bridge-ro-')
    copy = snapshot_database(db_path, work)
    if copy is None:
        return None
    conn = sqlite3.connect(f'file:{copy}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = _tables(conn)
        counts = {}
        for t in tables:
            counts[t] = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        schema = {t: _columns(conn, t) for t in tables}

        def rows(table):
            if table not in tables:
                return []
            return [dict(r) for r in conn.execute(f'SELECT * FROM "{table}"').fetchall()]

        return {'tables': counts, 'schema': schema,
                'tasks': rows('tasks'), 'runs': rows('runs'),
                'turns': rows('turns'), 'gates': rows('gates'),
                'artifacts': rows('artifacts'),
                'database_copy': str(copy)}
    finally:
        conn.close()


def read_apply_manifests(artifacts_root):
    """Улики доставки С ДИСКА. Это второй носитель, и он не смешивается с базой."""
    root = Path(artifacts_root)
    if not root.is_dir():
        return []
    out = []
    for man in sorted(root.glob('*/apply/manifest.json')):
        try:
            doc = json.loads(man.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        post = doc.get('post') or {}
        out.append({
            'run_dir': man.parent.parent.name,
            'run_id': doc.get('run_id'),
            'task_id': doc.get('task_id'),
            'status': doc.get('status'),
            'apply_commit': doc.get('apply_commit'),
            'diff_sha256': doc.get('diff_sha256'),
            'anchor': doc.get('anchor'),
            'revision': doc.get('revision'),
            # Личность НЕ выносится: наружу идёт только факт подтверждения.
            'owner_confirmed': bool(doc.get('confirmed_by')),
            'owner_identity_column': 'confirmed_by',
            'tests_passed': post.get('tests_passed'),
            'files_match': post.get('files_match'),
            'worktree_clean': post.get('clean'),
        })
    return out


def verify_commit(commit, repositories, *, runner=None):
    """Существует ли коммит на самом деле. Только чтение: ни checkout, ни fetch."""
    if not commit:
        return {'state': 'NOT_MEASURED', 'reason': 'идентификатор коммита не объявлен'}
    existing = [r for r in repositories if Path(r).is_dir()]
    if not existing:
        # «Не нашли, потому что негде было искать» — это не отсутствие коммита.
        return {'state': 'NOT_MEASURED',
                'reason': 'ни один репозиторий для сверки не подан или не существует'}
    run = runner or (lambda args: subprocess.run(args, capture_output=True, text=True,
                                                 timeout=20))
    checked = []
    for repo in existing:
        checked.append(Path(repo).name)
        try:
            probe = run(['git', '-C', str(repo), 'cat-file', '-t', commit])
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode != 0 or (probe.stdout or '').strip() != 'commit':
            continue
        try:
            info = run(['git', '-C', str(repo), 'show', '--no-patch',
                        '--format=%H%x1f%cI%x1f%s', commit])
            parts = (info.stdout or '').strip().split('\x1f')
        except (OSError, subprocess.SubprocessError):
            parts = []
        return {'state': 'EXISTS', 'repository': Path(repo).name,
                'commit': parts[0] if parts else commit,
                'committed_at': parts[1] if len(parts) > 1 else None,
                'subject': parts[2] if len(parts) > 2 else None}
    return {'state': 'NOT_FOUND', 'repositories_checked': checked,
            'reason': 'коммит не найден ни в одном из проверенных репозиториев: '
                      + ', '.join(checked)}


def _turn_kinds(turns, task_id):
    """Ходы задачи по фазам. Соединение по ``task_id`` — так устроена таблица."""
    kinds = {}
    for t in turns:
        if str(t.get('task_id') or '') != str(task_id):
            continue
        kind = str(t.get('phase') or 'UNKNOWN')
        status = str(t.get('status') or 'UNKNOWN')
        kinds.setdefault(kind, {'total': 0, 'done': 0})
        kinds[kind]['total'] += 1
        if status == 'done':
            kinds[kind]['done'] += 1
    return kinds


def build_bridge_evidence(*, db_path, artifacts_root, repositories=(), now=None,
                          git_runner=None):
    """Полная проекция моста из улик. Ни одно число не подаётся снаружи."""
    now = now or _now()
    db = read_database(db_path)
    if db is None:
        return {'schema': 'bridge_evidence/1', 'state': 'NOT_MEASURED',
                'reason': 'база моста не найдена — это НЕ значит, что моста нет',
                'measured_at': now.isoformat()}
    manifests = read_apply_manifests(artifacts_root)
    # Соединение манифеста с задачей — ТОЛЬКО по ``run_id``, совпадающему дословно.
    # Поле ``task_id`` в манифесте — человеческий слаг в верхнем регистре
    # (``IMPLEMENT-RFC054-T3.2b.2``), а в базе — машинный идентификатор с временем
    # (``implement-rfc054-t3-2b-2-1784765319-t1``). Сводить их подгонкой написания
    # значило бы склеивать записи по похожести имени — запрещено.
    by_run_manifest = {}
    for m in manifests:
        key = str(m.get('run_id') or '').strip()
        if key:
            by_run_manifest.setdefault(key, []).append(m)

    tasks, population = [], {s: 0 for s in STAGES}
    commit_checks = []
    for task in db['tasks']:
        tid = str(task.get('task_id') or '')
        rid = str(task.get('run_id') or '')
        runs = [r for r in db['runs'] if str(r.get('run_id') or '') == rid]
        gates = [g for g in db['gates'] if str(g.get('task_id') or '') == tid]
        kinds = _turn_kinds(db['turns'], tid)
        mans = by_run_manifest.get(rid, [])
        applied = [m for m in mans if m.get('status') == 'applied' and m.get('apply_commit')]

        # Стадия засчитывается ТОЛЬКО по своему носителю.
        proven = {
            'CREATED': ('DB', bool(tid)),
            'INTAKE': ('NO_CARRIER', None),
            'PLANNED': ('DB', kinds.get('plan', {}).get('done', 0) > 0),
            'EXECUTED': ('DB', kinds.get('implement', {}).get('done', 0) > 0),
            'REVIEWED': ('DB', kinds.get('review', {}).get('done', 0) > 0),
            'OWNER_GATE': ('DB', any(str(g.get('status') or '') == 'approved' for g in gates)),
            'OUTPUT': ('DISK', bool(mans)),
            'COMMIT': ('DISK', bool(applied)),
            'CANONICAL_DELIVERY': ('DISK+GIT', None),
        }
        verified = []
        for m in applied:
            check = verify_commit(m['apply_commit'], repositories, runner=git_runner)
            check['task_id'] = tid
            check['tests_passed'] = m.get('tests_passed')
            commit_checks.append(check)
            verified.append(check)
        proven['CANONICAL_DELIVERY'] = (
            'DISK+GIT', any(v.get('state') == 'EXISTS' for v in verified) if verified else None)

        furthest, furthest_carrier = None, None
        for stage in STAGES:
            carrier, ok = proven[stage]
            if ok:
                furthest, furthest_carrier = stage, carrier
        for stage in STAGES:
            if proven[stage][1]:
                population[stage] += 1
        tasks.append({
            'task_id': tid,
            'status': task.get('status'),
            'created_at': task.get('created_at'),
            'run_count': len(runs),
            'run_id': rid,
            'run_statuses': sorted({str(r.get('status') or 'UNKNOWN') for r in runs}),
            'turns_by_kind': kinds,
            'gate_count': len(gates),
            'gate_statuses': sorted({str(g.get('status') or 'UNKNOWN') for g in gates}),
            'gates_owner_confirmed': sum(1 for g in gates if g.get('decided_by')),
            'apply_manifests': len(mans),
            'manifest_join_key': 'run_id (дословное совпадение)',
            'commits_claimed': [m['apply_commit'] for m in applied],
            'commits_verified': verified,
            'tests_passed_on_delivery': [m.get('tests_passed') for m in applied],
            'stage_evidence': {s: {'carrier': proven[s][0], 'proven': proven[s][1]}
                               for s in STAGES},
            'furthest_proven_stage': furthest,
            'furthest_proven_carrier': furthest_carrier,
        })

    db_furthest = None
    for stage in STAGES:
        if any(t['stage_evidence'][stage]['proven'] and
               t['stage_evidence'][stage]['carrier'] == 'DB' for t in tasks):
            db_furthest = stage
    disk_furthest = None
    for stage in STAGES:
        if any(t['stage_evidence'][stage]['proven'] and
               t['stage_evidence'][stage]['carrier'] != 'DB' for t in tasks):
            disk_furthest = stage

    delivered = [c for c in commit_checks if c.get('state') == 'EXISTS']
    return {
        'schema': 'bridge_evidence/1',
        'state': 'READ',
        'measured_at': now.isoformat(),
        'table_counts': db['tables'],
        'tasks': tasks,
        'task_count': len(tasks),
        'run_count': len(db['runs']),
        'turn_count': len(db['turns']),
        'gate_count': len(db['gates']),
        'gates_approved': sum(1 for g in db['gates']
                              if str(g.get('status') or '') == 'approved'),
        # Отсутствие таблицы и пустая таблица — разные вещи. `None` значит «носителя
        # нет», ноль — «носитель есть и пуст». Слить их значило бы объявить измеренным
        # то, чего никто не мерил.
        'artifacts_table_rows': db['tables'].get('artifacts'),
        'artifacts_table_exists': 'artifacts' in db['tables'],
        'apply_manifests_on_disk': len(manifests),
        'stage_population': population,
        'furthest_proven_by_database': db_furthest,
        'furthest_proven_by_disk_evidence': disk_furthest,
        'carrier_note':
            'у стадий РАЗНЫЕ носители улик. База не содержит колонок ни под коммит, ни '
            'под репозиторий, поэтому дальше одобрения владельцем она не доказывает '
            'ничего. Коммиты доказывает каталог прогона, и это ДРУГАЯ улика',
        'commits_verified': delivered,
        'commits_verified_count': len(delivered),
        # Где ИСКАЛИ. Без этого число подтверждённых доставок нельзя сравнить с чужим
        # замером: тот, кому дали меньше репозиториев, найдёт меньше и будет прав.
        'repositories_checked': sorted({Path(r).name for r in repositories
                                        if Path(r).is_dir()}),
        'commits_not_found': [c for c in commit_checks if c.get('state') == 'NOT_FOUND'],
        'delivered_with_failing_tests': [
            c for c in delivered if c.get('tests_passed') is False],
        'contract_gaps': [dict(g) for g in CONTRACT_GAPS],
        'contract_gap_count': len(CONTRACT_GAPS),
        'identity_columns_blocked': list(IDENTITY_COLUMNS),
        'identity_note':
            'идентификатор владельца существует в улике и НЕ выносится наружу ни в '
            'каком виде: публикуется только признак подтверждения и имя колонки',
    }
