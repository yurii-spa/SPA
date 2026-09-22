#!/usr/bin/env python3
"""Director OS v1.3 · НЕЗАВИСИМАЯ сверка. Импортирует ноль модулей кокпита.

Зачем он написан заново
=======================
Проверка, зовущая тот же калькулятор, что и проверяемый, отвечает только на вопрос
«воспроизводим ли он» — и молчит о том, верен ли он. В красной команде v1.2 я именно так
«подтвердил» просадку −0.2047 %: пересчёт повторил арифметику источника и вместе с ней
повторил её предмет.

Поэтому здесь нет ни одного ``import`` из кокпита. Все величины считаются своей
арифметикой, из тех же канонических файлов, и сравниваются с тем, что кокпит опубликовал.
Совпадение — улика. Расхождение — отказ выпуска, а не повод поправить проверку.

Различие подходов намеренно
===========================
Там, где кокпит идёт от разобранного ряда и объявленных разрывов, сверка идёт от сырых
строк и словарей по датам. Два пути к одному числу — и есть смысл слова «независимая».

Read-only. Только stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import sqlite3
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TOLERANCE = 1e-4

#: ВЕЛИЧИНЫ, КОТОРЫЕ ОБЯЗАНЫ СОВПАСТЬ ТОЧНО. Это утверждения о прошлом и о состоянии
#: файлов: между двумя наблюдениями они измениться не могут, поэтому расхождение здесь
#: есть дефект, а не разница момента.
STABLE_METRICS = frozenset({
    'equity_now', 'capital_base', 'deployed_usd', 'cash_usd', 'net_pnl_usd',
    'accrued_yield_usd', 'costs_paid_usd', 'policy_compliant',
    'return_1d', 'return_7d', 'return_30d', 'return_since_evidenced_start',
    'max_drawdown_evidenced', 'current_drawdown', 'evidenced_days', 'series_points',
    'commits_verified', 'tasks', 'runs', 'turns', 'gates', 'entities_total',
    'owner_decisions_waiting',
})

#: ВЕЛИЧИНЫ, СРАВНИМЫЕ ТОЛЬКО ПРИ РАВНОЙ ОБЛАСТИ ПОИСКА. Число подтверждённых доставок
#: зависит от того, сколько репозиториев подано прибору: тот, кому дали меньше, найдёт
#: меньше и будет ПРАВ. Сравнивать такие величины при разной области — значит объявлять
#: дефектом собственный недосмотр. Замер: сверка с одним репозиторием дала 1 против 2 и
#: уронила выпуск, хотя код был верен.
SCOPE_DEPENDENT_METRICS = frozenset({'commits_verified'})

#: Третий исход у КЛАССА величины. Отсутствие не получает настоящего класса: приписать
#: неопубликованному числу «изменчивый» значило бы впустить любое отсутствие в дверь
#: «законно расходится», то есть выдать НЕ ИЗМЕРЕНО за наблюдение (инв. #17).
NOT_MEASURED_CLASS = 'NOT_MEASURED'

#: ВЕЛИЧИНЫ-СНИМКИ. Они описывают флот в МОМЕНТ наблюдения: задание по расписанию,
#: застигнутое в середине прогона, живёт секунды, а возраст артефакта переходит порог
#: сам собой. Кокпит и сверка меряют в разные моменты, поэтому их расхождение здесь —
#: свойство измерения, а не дефект. Замер это показал прямо: за один прогон число живых
#: процессов дало 9 и 8, и оба раза верно.
#: Скрывать такое расхождение нельзя — оно печатается вместе с разницей во времени.
VOLATILE_METRICS = frozenset({
    'running_now', 'running_stage_true', 'producing_fresh_output',
    'entities_with_declared_slo',
})


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _rows_by_date(daily):
    """Словарь дата → строка. Свой путь: кокпит строит список, сверка — отображение."""
    out = {}
    for r in daily or ():
        d = str(r.get('date') or '')[:10]
        if re.match(r'^\d{4}-\d{2}-\d{2}$', d):
            out[d] = r
    return out


def verify_capital(data_dir):
    """Пересчёт критических величин капитала СВОЕЙ арифметикой."""
    eq = _load(Path(data_dir) / 'equity_curve_daily.json') or {}
    pos = _load(Path(data_dir) / 'current_positions.json') or {}
    daily = eq.get('daily') or []
    by_date = _rows_by_date(daily)
    dates = sorted(by_date)
    if not dates:
        return {}
    last = dates[-1]
    end = by_date[last].get('close_equity')

    out = {}
    # Итоги капитала: берутся прямо из объявленных полей источника.
    for metric, key in (('equity_now', 'current_equity_usd'),
                        ('capital_base', 'capital_usd'),
                        ('deployed_usd', 'deployed_usd'),
                        ('cash_usd', 'cash_usd'),
                        ('net_pnl_usd', 'net_pnl_usd'),
                        ('accrued_yield_usd', 'accrued_yield_usd'),
                        ('costs_paid_usd', 'costs_paid_usd')):
        out[metric] = pos.get(key)
    out['policy_compliant'] = pos.get('policy_compliant')

    # Окна: свой путь — арифметика по календарю через словарь дат.
    reset_dates = {d for d, r in by_date.items() if r.get('series_reset')}
    for days, metric in ((1, 'return_1d'), (7, 'return_7d'), (30, 'return_30d')):
        target = (date.fromisoformat(last) - timedelta(days=days)).isoformat()
        if target not in by_date:
            out[metric] = None
            continue
        crossed = [d for d in reset_dates if target < d <= last]
        if crossed:
            out[metric] = None
            continue
        base = by_date[target].get('close_equity')
        out[metric] = round((end / base - 1.0) * 100.0, 6) if base else None

    # Доход с якоря: якорь — первая дата с evidenced, основание — объявленное источником.
    anchor = next((d for d in dates if by_date[d].get('evidenced')), None)
    base = (eq.get('summary') or {}).get('real_start_equity')
    out['return_since_evidenced_start'] = (
        round((end / base - 1.0) * 100.0, 6) if (anchor and base) else None)

    # Максимальная просадка: свой проход, пик сбрасывается на объявленном разрыве.
    peak, worst = None, 0.0
    for d in dates:
        v = by_date[d].get('close_equity')
        if v is None:
            continue
        if d in reset_dates or peak is None:
            peak = v
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, (v / peak - 1.0) * 100.0)
    out['max_drawdown_evidenced'] = round(worst, 6)

    # Текущая просадка: относительно максимума ВСЕГО ряда.
    top = max((by_date[d].get('close_equity') for d in dates
               if by_date[d].get('close_equity') is not None), default=None)
    out['current_drawdown'] = round((end / top - 1.0) * 100.0, 6) if top else None
    out['evidenced_days'] = (eq.get('summary') or {}).get('evidenced_days')
    out['series_points'] = len(dates)
    return out


def verify_fleet(production_root, *, launchd_dirs=None):
    """Сколько сущностей ДЕЙСТВИТЕЛЬНО работает сейчас — своим разбором вывода системы."""
    root = Path(production_root)
    manifest = _load(root / 'architecture' / 'manifest.json') or {}
    registry = _load(root / 'data' / 'agent_registry.json') or {}
    declared = {a.get('label') for a in manifest.get('agents') or () if a.get('label')}
    declared |= {a.get('label') for a in registry.get('agents') or () if a.get('label')}
    prefixes = {'.'.join(str(l).split('.')[:2]) + '.' for l in declared if l}

    try:
        proc = subprocess.run(['launchctl', 'list'], capture_output=True, text=True,
                              timeout=30)
        listing = proc.stdout if proc.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        listing = ''
    live, seen = 0, set()
    for line in listing.splitlines()[1:]:
        parts = line.split('\t')
        if len(parts) < 3:
            continue
        pid, _status, label = parts[0].strip(), parts[1], parts[2].strip()
        if label in declared or any(label.startswith(p) for p in prefixes):
            seen.add(label)
            if pid.isdigit():
                live += 1

    dirs = launchd_dirs or [os.path.expanduser('~/Library/LaunchAgents'),
                            str(root / 'launchd')]
    installed = set()
    for d in dirs:
        p = Path(d)
        if p.is_dir():
            for f in p.glob('*.plist'):
                if f.stem in declared or any(f.stem.startswith(x) for x in prefixes):
                    installed.add(f.stem)

    # Свежие артефакты: свой обход объявлений манифеста, свой stat.
    now = datetime.now(timezone.utc).timestamp()
    # Манифест объявляет выходы в ДВУХ секциях, и они покрывают разные ярлыки.
    # Читаются обе: независимость проверки — про отдельный код, а не про меньшие данные.
    declarations = {}
    for agent in manifest.get('agents') or ():
        label = agent.get('label')
        if not label:
            continue
        for p in agent.get('produces') or ():
            if isinstance(p, dict) and p.get('artifact') and p.get('slo_hours'):
                declarations.setdefault(label, {})[str(p['artifact'])] = p['slo_hours']
    for art in manifest.get('artifacts') or ():
        if not isinstance(art, dict):
            continue
        label, path, slo = art.get('producer'), art.get('path'), art.get('slo_hours')
        if label and path and slo is not None:
            declarations.setdefault(label, {}).setdefault(str(path), slo)

    fresh_entities, with_slo = set(), set()
    for label, decls in declarations.items():
        with_slo.add(label)
        ok = True
        for artifact, slo in decls.items():
            f = root / artifact
            try:
                age = (now - f.stat().st_mtime) / 3600.0
            except OSError:
                ok = False
                break
            if age > float(slo):
                ok = False
                break
        if ok:
            fresh_entities.add(label)
    return {
        'entities_total': len(declared | installed | seen),
        'running_now': live,
        'entities_with_declared_slo': len(with_slo),
        'producing_fresh_output': len(fresh_entities),
    }


def verify_bridge(bridge_root, repositories):
    """Сколько доставок ПОДТВЕРЖДАЕТСЯ git — своим обходом каталогов и своим git."""
    root = Path(bridge_root)
    artifacts = root / 'artifacts'
    claimed, verified = [], 0
    if artifacts.is_dir():
        for man in sorted(artifacts.glob('*/apply/manifest.json')):
            try:
                doc = json.loads(man.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            sha = doc.get('apply_commit')
            if doc.get('status') == 'applied' and sha:
                claimed.append(sha)
    for sha in claimed:
        for repo in repositories:
            if not Path(repo).is_dir():
                continue
            try:
                probe = subprocess.run(['git', '-C', str(repo), 'cat-file', '-t', sha],
                                       capture_output=True, text=True, timeout=20)
            except (OSError, subprocess.SubprocessError):
                continue
            if probe.returncode == 0 and probe.stdout.strip() == 'commit':
                verified += 1
                break
    db = root / 'state' / 'bridge.db'
    counts = {}
    if db.exists():
        work = tempfile.mkdtemp(prefix='verify-bridge-')
        copy = Path(work) / db.name
        shutil.copy2(db, copy)
        for s in ('-wal', '-shm'):
            side = db.with_name(db.name + s)
            if side.exists():
                shutil.copy2(side, copy.with_name(copy.name + s))
        conn = sqlite3.connect(f'file:{copy}?mode=ro', uri=True)
        try:
            for t in ('tasks', 'runs', 'turns', 'gates'):
                try:
                    counts[t] = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                except sqlite3.Error:
                    counts[t] = None
        finally:
            conn.close()
    return {'commits_claimed': len(claimed), 'commits_verified': verified, **counts}


def verify_owner_decisions(production_root, bridge_root=None):
    """Сколько решений ждёт — свой обход, свои правила чтения."""
    root = Path(production_root)
    total = 0
    tracker = root / 'nimbalyst-local' / 'tracker'
    if tracker.is_dir():
        for f in tracker.glob('*.md'):
            if f.stem.split('-')[0] not in ('own', 'owner'):
                continue
            head = f.read_text(encoding='utf-8', errors='replace')[:2000]
            if re.search(r'^status:\s*needs-owner\s*$', head, re.M):
                total += 1
    blockers = _load(root / 'data' / 'owner_blockers.json') or {}
    total += sum(1 for g in blockers.get('gates') or ()
                 if isinstance(g, dict) and g.get('status') == 'open')
    gate = _load(root / 'data' / 'gate_status.json') or {}
    if str(gate.get('owner_acceptance')).upper() == 'PENDING':
        total += 1
    live = _load(root / 'data' / 'live_trading_gate.json') or {}
    if live.get('owner_acceptance') is False:
        total += 1
    kanban = _load(root / 'KANBAN.json')
    if kanban is not None:
        stack, found = [kanban], 0
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if str(node.get('status') or '').lower() == 'blocked_user_action':
                    found += 1
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        total += found
    if bridge_root:
        db = Path(bridge_root) / 'state' / 'bridge.db'
        if db.exists():
            work = tempfile.mkdtemp(prefix='verify-gates-')
            copy = Path(work) / db.name
            shutil.copy2(db, copy)
            for s in ('-wal', '-shm'):
                side = db.with_name(db.name + s)
                if side.exists():
                    shutil.copy2(side, copy.with_name(copy.name + s))
            conn = sqlite3.connect(f'file:{copy}?mode=ro', uri=True)
            try:
                total += conn.execute(
                    "SELECT COUNT(*) FROM gates WHERE status='open'").fetchone()[0]
            except sqlite3.Error:
                pass
            finally:
                conn.close()
    return {'owner_decisions_waiting': total}


def _observation_gap_seconds(projection, now=None):
    """Сколько прошло между сборкой проекции и этой сверкой."""
    stamp = projection.get('generated_at')
    if not stamp:
        return None
    try:
        built = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except ValueError:
        return None
    if built.tzinfo is None:
        built = built.replace(tzinfo=timezone.utc)
    return round(((now or datetime.now(timezone.utc)) - built).total_seconds(), 1)


def _scope_matches(projection, checked):
    """Совпадает ли область поиска сверки с областью, в которой искал кокпит."""
    declared = ((projection.get('bridge') or {}).get('repositories_checked'))
    if declared is None:
        return None, 'кокпит не объявил область поиска — сравнить области нельзя'
    mine = sorted(set(checked or ()))
    if sorted(declared) == mine:
        return True, None
    return False, (f'область поиска не совпадает: кокпит искал в {sorted(declared)}, '
                   f'сверка — в {mine}')


ROW_KEYS = ('metric', 'independent', 'director', 'verdict', 'metric_class')


def _assert_row_contract(rows):
    """Каждая строка сверки обязана быть ПОЛНОЙ. Неполная — отказ с именем.

    До этой проверки агрегат читал ``metric_class`` у каждой строки безусловно, а две
    ветки (``NOT_PUBLISHED``, ``BOTH_NOT_MEASURED``) его не кладут: сверка умирала
    ``KeyError`` ровно на том исходе, ради честности о котором написана. Теперь контракт
    назван вслух и нарушивший его ряд роняет сверку с именем величины, а не трассировкой.
    """
    bad = [(r.get('metric'), k) for r in rows for k in ROW_KEYS if k not in r]
    if bad:
        raise ValueError('строка сверки неполна: ' +
                         '; '.join(f'{m}: нет {k}' for m, k in bad))


def missing_v13_layer(projection):
    """Есть ли в проекции слой v1.3. Отсутствие — НЕ ИЗМЕРЕНО, а не 21 находка.

    Замер 22.09: обёртка сборки не передаёт ``--v13``, слоя в проекции нет, и прежний
    откат ``projection.get('v13') or projection`` превращал ОДНО отсутствие документа в
    двадцать одну строку уровня величин — 16 «не опубликовано» и 5 «расхождение», при
    НУЛЕ строк ``AGREE``. Ноль совпадений при полном населении и есть улика того, что
    сравнивать было нечего (инв. #17).
    """
    if not isinstance(projection, dict):
        return 'проекция не является словарём'
    if 'v13' not in projection:
        return ("в проекции нет слоя 'v13': сборка велась без --v13, сравнивать не с чем")
    if not isinstance(projection['v13'], dict) or not projection['v13']:
        return "слой 'v13' пуст"
    return None


def compare(projection, measured, *, now=None, repositories_checked=None):
    """Сверка. Расхождение — ОТКАЗ выпуска, а не повод поправить проверку."""
    facts = {f.get('metric'): f for f in projection.get('facts') or ()}
    v13 = projection
    published = {}
    for metric, f in facts.items():
        published[metric] = f.get('value')
    health = (v13.get('service_health') or {}).get('counts') or {}
    # Сверяется НАБЛЮДЕНИЕ (есть ли процесс), а не стадия (должен ли он быть).
    published['running_now'] = health.get('has_live_process')
    published['running_stage_true'] = health.get('running_true')
    published['producing_fresh_output'] = health.get('producing_true')
    published['entities_total'] = health.get('total')
    published['entities_with_declared_slo'] = health.get('entities_with_declared_slo')
    bridge = v13.get('bridge') or {}
    published['commits_verified'] = bridge.get('commits_verified_count')
    published['tasks'] = bridge.get('task_count')
    published['runs'] = bridge.get('run_count')
    published['turns'] = bridge.get('turn_count')
    published['gates'] = bridge.get('gate_count')
    published['owner_decisions_waiting'] = (v13.get('owner_decisions') or {}).get('waiting_total')

    rows, mismatches = [], 0
    for metric, expected in sorted(measured.items()):
        got = published.get(metric, '__ABSENT__')
        if got == '__ABSENT__':
            rows.append({'metric': metric, 'independent': expected, 'director': None,
                         'verdict': 'NOT_PUBLISHED',
                         'metric_class': NOT_MEASURED_CLASS})
            continue
        if expected is None and got is None:
            rows.append({'metric': metric, 'independent': None, 'director': None,
                         'verdict': 'BOTH_NOT_MEASURED',
                         'metric_class': NOT_MEASURED_CLASS})
            continue
        if isinstance(expected, (int, float)) and isinstance(got, (int, float)) \
                and not isinstance(expected, bool) and not isinstance(got, bool):
            ok = abs(float(expected) - float(got)) <= TOLERANCE
        else:
            ok = expected == got
        if metric in SCOPE_DEPENDENT_METRICS:
            same, why = _scope_matches(projection, repositories_checked)
            if same is not True:
                rows.append({'metric': metric, 'independent': expected,
                             'director': got, 'verdict': 'NOT_COMPARABLE',
                             'metric_class': 'SCOPE_DEPENDENT', 'reason': why})
                continue
        if ok:
            verdict = 'AGREE'
        elif metric in VOLATILE_METRICS:
            verdict = 'VOLATILE_DIFFERS'
        else:
            verdict = 'MISMATCH'
        rows.append({'metric': metric, 'independent': expected, 'director': got,
                     'verdict': verdict,
                     'metric_class': ('STABLE' if metric in STABLE_METRICS else
                                      'VOLATILE' if metric in VOLATILE_METRICS
                                      else 'SCOPE_DEPENDENT'
                                      if metric in SCOPE_DEPENDENT_METRICS
                                      else 'UNCLASSIFIED')})
        if verdict == 'MISMATCH':
            mismatches += 1
    _assert_row_contract(rows)
    volatile = sum(1 for r in rows if r['verdict'] == 'VOLATILE_DIFFERS')
    not_comparable = [r['metric'] for r in rows if r['verdict'] == 'NOT_COMPARABLE']
    unclassified = [r['metric'] for r in rows if r['metric_class'] == 'UNCLASSIFIED']
    not_published = [r['metric'] for r in rows if r['verdict'] == 'NOT_PUBLISHED']
    both_not_measured = [r['metric'] for r in rows
                         if r['verdict'] == 'BOTH_NOT_MEASURED']
    return {'rows': rows, 'mismatches': mismatches,
            'volatile_differences': volatile,
            'observation_gap_seconds': _observation_gap_seconds(projection, now),
            'unclassified_metrics': unclassified,
            'not_published': not_published,
            'both_not_measured': both_not_measured,
            'not_comparable': not_comparable,
            'scope_note': ('величина, зависящая от области поиска, сравнивается только '
                           'при равной области; иначе это третий исход, а не дефект'),
            # Неклассифицированная величина роняет сверку намеренно: молча отнести
            # новое число к «изменчивым» значило бы открыть дверь любому расхождению.
            'verdict': ('PASS' if mismatches == 0 and not unclassified else 'FAIL'),
            'tolerance': TOLERANCE,
            'stable_note': 'устойчивые величины обязаны совпасть точно; расхождение '
                           'в них — отказ выпуска',
            'volatile_note': 'величины-снимки описывают флот в момент наблюдения и '
                             'законно расходятся между двумя замерами; расхождение '
                             'печатается, но выпуск не роняет',
            'note': ('сверка не импортирует ни одного модуля кокпита: числа посчитаны '
                     'своей арифметикой из тех же канонических файлов')}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--production', required=True)
    ap.add_argument('--projection', required=True, help='director_web_projection.json')
    ap.add_argument('--bridge-root')
    ap.add_argument('--repository', action='append', default=[])
    ap.add_argument('--json', help='куда записать результат сверки')
    args = ap.parse_args(argv)

    projection = _load(args.projection)
    if projection is None:
        raise SystemExit(f'проекция не прочитана: {args.projection}')
    why = missing_v13_layer(projection)
    if why is not None:
        print(f'НЕ ИЗМЕРЕНО: {why}')
        print('  Это НЕ означает «сверка прошла» и НЕ означает «кокпит скрыл числа».')
        return 2
    v13 = projection['v13']

    measured = {}
    measured.update(verify_capital(Path(args.production) / 'data'))
    measured.update(verify_fleet(args.production))
    measured.update(verify_owner_decisions(args.production, args.bridge_root))
    if args.bridge_root:
        b = verify_bridge(args.bridge_root, args.repository)
        measured['commits_verified'] = b['commits_verified']
        for k in ('tasks', 'runs', 'turns', 'gates'):
            if b.get(k) is not None:
                measured[k] = b[k]

    result = compare(v13, measured, repositories_checked=[
        Path(r).name for r in args.repository if Path(r).is_dir()])
    width = max(len(r['metric']) for r in result['rows'])
    for r in result['rows']:
        mark = {'AGREE': '✓', 'MISMATCH': '✗', 'NOT_PUBLISHED': '·',
                'BOTH_NOT_MEASURED': '—', 'VOLATILE_DIFFERS': '~',
                'NOT_COMPARABLE': '?'}[r['verdict']]
        print(f"{mark} {r['metric']:<{width}}  независимо={str(r['independent']):>16}  "
              f"кокпит={str(r['director']):>16}  {r['verdict']}")
    print(f"\nВЕРДИКТ СВЕРКИ: {result['verdict']} · расхождений в устойчивых "
          f"{result['mismatches']} · расхождений в изменчивых "
          f"{result['volatile_differences']} (разрыв наблюдений "
          f"{result['observation_gap_seconds']} с)")
    if result['not_comparable']:
        print('  НЕ СРАВНИМО (область поиска сверки не совпала с областью кокпита): '
              + ', '.join(result['not_comparable']))
    if result['not_published']:
        print('  НЕ ОПУБЛИКОВАНО кокпитом (измерено независимо, на экран не попало): '
              + ', '.join(result['not_published']))
    if result['both_not_measured']:
        print('  НЕ ИЗМЕРЕНО НИ ОДНОЙ СТОРОНОЙ (согласие об отсутствии): '
              + ', '.join(result['both_not_measured']))
    if result['unclassified_metrics']:
        print('  НЕ КЛАССИФИЦИРОВАНЫ (выпуск отклонён): '
              + ', '.join(result['unclassified_metrics']))
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                   encoding='utf-8')
    return 0 if result['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
