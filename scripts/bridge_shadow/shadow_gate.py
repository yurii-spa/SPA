#!/usr/bin/env python3
"""Studio Bridge · ТЕНЕВОЙ режим нового гейта доставки.

Что такое теневой режим
=======================
Новый механизм НИЧЕГО не решает. Старый путь продолжает управлять, а новый лишь
записывает, что он СДЕЛАЛ БЫ — ``WOULD_ALLOW`` / ``WOULD_BLOCK`` — и почему. Затем
решения сравниваются.

Почему просто «прогнать на истории» недостаточно
================================================
Ретроспективный прогон по шести настоящим доставкам даёт шесть отказов, и это ничего
не доказывает: у исторических улик нет вердикта тестов в РЕШАЮЩЕЙ фазе, потому что
тогда его не снимали. Гейт отказывает за отсутствие улики — верно и неинформативно.
«Ноль совпадений» здесь был бы пустым по построению.

Поэтому сравнение устроено в два слоя:

1. **Ретроспективный** — на настоящих событиях. Каждый отказ обязан НАЗВАТЬ, какой
   улики не хватило. Это доказывает, что гейт не произволен, а не то, что он различает.
2. **Различающий** — на событиях, собранных так, чтобы покрыть и допуск, и отказ.
   Это доказывает, что гейт различает.

Классификация расхождений
=========================
Расхождение «старый путь пустил, новый бы заблокировал» — **ожидаемое**, в нём и смысл
усиления; но оно обязано быть объяснено названной причиной. Расхождение «старый путь
заблокировал, новый бы пустил» — **ослабление** и недопустимо ни в одном случае.

Ничего не пишет в боевые каталоги. Только stdlib.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

#: Прототип принят ARB и лежит рядом; путь объявляется, а не угадывается.
PROTOTYPE = Path.home() / 'studio-os-scratch' / 'bridge-integrity'
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from bridge import delivery_integrity as di          # noqa: E402

SCHEMA = 'bridge_shadow/1'

# Классы расхождения и вердикт живут В ОДНОЙ копии — у соседа, который не зависит от
# прототипа и потому исполняется в CI. Здесь только проводка.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import shadow_verdict as _SV                        # noqa: E402
from shadow_verdict import (                       # noqa: E402
    WOULD_ALLOW, WOULD_BLOCK, OLD_ALLOWED, OLD_BLOCKED, OLD_UNKNOWN,
    UNEXPLAINED, WEAKENING, EXIT_CODE, SourceNotRead,
    classify_mismatch, shadow_verdict,
)


def _utcnow():
    return datetime.now(timezone.utc)


def read_production_events(*, db_path, artifacts_root):
    """События, эквивалентные боевым: то, что мост действительно делал.

    База читается на КОПИИ вместе со спутниками: без ``-wal`` прочиталась бы база
    многонедельной давности.
    """
    work = tempfile.mkdtemp(prefix='shadow-ro-')
    src = Path(db_path)
    if not src.exists():
        # Пустой список означал бы «база прочитана и пуста». Это РАЗНЫЕ утверждения,
        # и на их слиянии вердикт объявлял чистым прогон, не прочитавший ничего.
        raise SourceNotRead(f'базы моста нет на объявленном пути: {src}')
    dst = Path(work) / src.name
    shutil.copy2(src, dst)
    for suffix in ('-wal', '-shm'):
        side = src.with_name(src.name + suffix)
        if side.exists():
            shutil.copy2(side, dst.with_name(dst.name + suffix))
    conn = sqlite3.connect(f'file:{dst}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tasks = [dict(r) for r in conn.execute('SELECT * FROM tasks')]
        turns = [dict(r) for r in conn.execute('SELECT * FROM turns')]
        gates = [dict(r) for r in conn.execute('SELECT * FROM gates')]
    finally:
        conn.close()

    manifests = {}
    root = Path(artifacts_root)
    if root.is_dir():
        for man in sorted(root.glob('*/apply/manifest.json')):
            try:
                doc = json.loads(man.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            key = str(doc.get('run_id') or '')
            if key:
                manifests[key] = doc

    events = []
    for task in tasks:
        tid, rid = str(task.get('task_id') or ''), str(task.get('run_id') or '')
        phases = {}
        for t in turns:
            if str(t.get('task_id') or '') != tid:
                continue
            phases.setdefault(str(t.get('phase') or ''), []).append(str(t.get('status') or ''))
        gl = [g for g in gates if str(g.get('task_id') or '') == tid]
        man = manifests.get(rid)
        # Что СДЕЛАЛ старый путь — записано, а не предполагается.
        if man and man.get('status') == 'applied' and man.get('apply_commit'):
            old = OLD_ALLOWED
        elif str(task.get('status') or '') == 'failed':
            old = OLD_BLOCKED
        else:
            old = OLD_UNKNOWN
        events.append({
            'task_id': tid, 'run_id': rid, 'old_decision': old,
            'task_status': task.get('status'),
            'phases_done': {k: v.count('done') for k, v in phases.items()},
            'gates': [{'status': g.get('status')} for g in gl],
            'manifest': ({'diff_sha256': man.get('diff_sha256'),
                          'apply_commit': man.get('apply_commit'),
                          'files_match': (man.get('post') or {}).get('files_match'),
                          'tests_passed': (man.get('post') or {}).get('tests_passed'),
                          'tests_tail': (man.get('post') or {}).get('tests_tail') or ''}
                         if man else None),
            'tree_hash_before': task.get('tree_hash_before'),
        })
    return events


def shadow_decide(event, *, target):
    """Что сделал бы НОВЫЙ гейт. Ничего не исполняет."""
    man = event.get('manifest') or {}
    tail = man.get('tests_tail') or ''
    # Вердикт тестов из исторической улики разбирается трёхзначно и в ТОЙ фазе,
    # в которой он был снят, — а снят он был после коммита.
    if man.get('tests_passed') is None:
        verdict = None
    else:
        verdict = di.classify_test_run(
            exit_code=0 if man.get('tests_passed') else 1, timed_out=False,
            output=tail, phase=di.PHASE_POST_COMMIT)
    done = event.get('phases_done') or {}
    gl = event.get('gates') or []
    facts = di.DeliveryFacts(
        task_id=event['task_id'] or '?', run_id=event['run_id'] or '?',
        diff_sha256=man.get('diff_sha256') or '', target=target,
        test_verdict=verdict,
        execution_done=(done.get('implement', 0) > 0) or None,
        review_done=(done.get('review', 0) > 0) or None,
        owner_gate_required=(True if gl else None),
        owner_gate_approved=(any(g['status'] == 'approved' for g in gl) if gl else None),
        tree_hash_before=event.get('tree_hash_before'),
        paths_allowed=man.get('files_match'),
        diff_present=bool(man.get('diff_sha256')))
    auth, refusals = di.evaluate_delivery_gate(facts)
    return {'shadow_decision': WOULD_ALLOW if auth else WOULD_BLOCK,
            'why': refusals if refusals else ['все условия доставки выполнены'],
            'test_verdict': None if verdict is None else verdict.verdict,
            'test_phase': None if verdict is None else verdict.phase}


def run_shadow(*, db_path, artifacts_root, target, now=None):
    now = now or _utcnow()
    try:
        events = read_production_events(db_path=db_path, artifacts_root=artifacts_root)
        source_read = True
    except SourceNotRead as exc:
        events, source_read, source_refusal = [], False, str(exc)
    rows, counts = [], {}
    for ev in events:
        out = shadow_decide(ev, target=target)
        kind = classify_mismatch(ev['old_decision'], out['shadow_decision'], out['why'])
        counts[kind] = counts.get(kind, 0) + 1
        rows.append({**{k: ev[k] for k in ('task_id', 'run_id', 'old_decision',
                                           'task_status')},
                     **out, 'mismatch': kind})
    verdict, why_verdict = shadow_verdict(counts, events=len(rows),
                                         source_read=source_read)
    if not source_read:
        why_verdict = source_refusal
    return {
        'schema': SCHEMA,
        'mode': 'SHADOW — новый механизм ничего не решает',
        'measured_at': now.isoformat(),
        'events': len(rows),
        'rows': rows,
        'would_allow': sum(1 for r in rows if r['shadow_decision'] == WOULD_ALLOW),
        'would_block': sum(1 for r in rows if r['shadow_decision'] == WOULD_BLOCK),
        'by_mismatch': counts,
        'unexplained': [r['task_id'] for r in rows if r['mismatch'] == UNEXPLAINED],
        'weakening': [r['task_id'] for r in rows if r['mismatch'] == WEAKENING],
        'verdict': verdict,
        'why_verdict': why_verdict,
        'source_read': source_read,
        'compared': sum(counts.get(k, 0) for k in _SV.COMPARED),
        'not_compared': sum(counts.get(k, 0) for k in _SV.NOT_COMPARED),
        'unknown_classes': sorted(k for k in counts if k not in _SV.MISMATCH_CLASSES),
        'retrospective_caveat': (
            'у исторических улик нет вердикта тестов в решающей фазе — тогда его не '
            'снимали. Поэтому отказы здесь ожидаемы и доказывают лишь, что гейт не '
            'произволен: каждый называет недостающую улику. Что он РАЗЛИЧАЕТ, '
            'доказывает второй слой сравнения'),
        'weakening_rule': 'ослабление недопустимо ни в одном случае',
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--bridge-root', required=True)
    ap.add_argument('--target-repo', required=True)
    ap.add_argument('--target-name', default='canon')
    ap.add_argument('--json')
    args = ap.parse_args(argv)
    root = Path(args.bridge_root)
    target = di.CanonicalTarget(name=args.target_name, repo_root=args.target_repo)
    out = run_shadow(db_path=root / 'state' / 'bridge.db',
                     artifacts_root=root / 'artifacts', target=target)
    print(f"ТЕНЕВОЙ ПРОГОН · событий {out['events']} · "
          f"WOULD_ALLOW {out['would_allow']} · WOULD_BLOCK {out['would_block']}")
    print(f"расхождения: {out['by_mismatch']}")
    for r in out['rows']:
        print(f"  {r['task_id'][:44]:<44} старый={r['old_decision']:<12} "
              f"новый={r['shadow_decision']:<12} {r['mismatch']}")
        if r['mismatch'] in (UNEXPLAINED, WEAKENING):
            for w in r['why']:
                print(f"{'':>48}! {w[:96]}")
    print(f"\nВЕРДИКТ ТЕНИ: {out['verdict']} · сравнений {out['compared']} · "
          f"без записанного старого решения {out['not_compared']} · необъяснённых "
          f"{len(out['unexplained'])} · ослаблений {len(out['weakening'])}")
    print(f"  причина: {out['why_verdict']}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                   encoding='utf-8')
    # 0 — измерено и чисто, 1 — находка, 2 — НЕ ИЗМЕРЕНО. Прежний код
    # возврата знал только два исхода и на «не измерено» отвечал нулём.
    return EXIT_CODE[out['verdict']]


if __name__ == '__main__':
    raise SystemExit(main())


# ── Второй слой: РАЗЛИЧАЮЩИЕ события ─────────────────────────────────────────

def discriminating_events(repo_root):
    """События, собранные так, чтобы покрыть и допуск, и отказ.

    Первый слой даёт ``WOULD_ALLOW 0`` — и это ничего не говорит о различении: гейт
    отказывает всем, потому что у исторических улик нет вердикта тестов в решающей
    фазе. «Ноль допусков» там пуст по построению.

    Здесь события эквивалентны боевым по СОСТАВУ улик, но вердикт снят в решающей
    фазе — как его будет снимать боевой путь после переноса. Один допуск и по одному
    отказу на каждое условие: тогда «различает» становится измеренным.
    """
    ok = di.TestVerdict(di.PASSED, di.PHASE_PRE_COMMIT, exit_code=0)
    red = di.TestVerdict(di.FAILED, di.PHASE_PRE_COMMIT, exit_code=1,
                         reason='тесты завершились с кодом 1')
    absent = di.classify_test_run(exit_code=1, timed_out=False,
                                  output='No module named pytest',
                                  phase=di.PHASE_PRE_COMMIT)
    late = di.TestVerdict(di.PASSED, di.PHASE_POST_COMMIT, exit_code=0)
    base = dict(execution_done=True, review_done=True, owner_gate_required=False,
                owner_gate_approved=None, tree_hash_before='tree-before',
                paths_allowed=True, diff_present=True)
    return [
        ('полная доставка', dict(base, test_verdict=ok), WOULD_ALLOW),
        ('красные тесты', dict(base, test_verdict=red), WOULD_BLOCK),
        ('инструмента тестов нет', dict(base, test_verdict=absent), WOULD_BLOCK),
        ('вердикт после коммита', dict(base, test_verdict=late), WOULD_BLOCK),
        ('вердикта нет', dict(base, test_verdict=None), WOULD_BLOCK),
        ('нет отпечатка дерева', dict(base, test_verdict=ok, tree_hash_before=None),
         WOULD_BLOCK),
        ('исполнение не измерено', dict(base, test_verdict=ok, execution_done=None),
         WOULD_BLOCK),
        ('ревью не было', dict(base, test_verdict=ok, review_done=False), WOULD_BLOCK),
        ('пути вне разрешённых', dict(base, test_verdict=ok, paths_allowed=False),
         WOULD_BLOCK),
        ('одобрение не измерено', dict(base, test_verdict=ok,
                                       owner_gate_required=None), WOULD_BLOCK),
        ('гейт нужен и не одобрен', dict(base, test_verdict=ok,
                                         owner_gate_required=True,
                                         owner_gate_approved=False), WOULD_BLOCK),
        ('диффа нет', dict(base, test_verdict=ok, diff_present=False), WOULD_BLOCK),
        # Одобренный гейт обязан ПУСКАТЬ, иначе гейт бессмыслен.
        ('гейт нужен и одобрен', dict(base, test_verdict=ok,
                                      owner_gate_required=True,
                                      owner_gate_approved=True), WOULD_ALLOW),
    ]


def run_discriminating(*, target, now=None):
    now = now or _utcnow()
    rows, wrong = [], []
    for name, kw, expected in discriminating_events(target.repo_root):
        facts = di.DeliveryFacts(task_id='SHADOW', run_id='R', diff_sha256='d' * 64,
                                 target=target, **kw)
        auth, refusals = di.evaluate_delivery_gate(facts)
        got = WOULD_ALLOW if auth else WOULD_BLOCK
        agrees = got == expected
        rows.append({'event': name, 'expected': expected, 'shadow_decision': got,
                     'agrees': agrees,
                     'why': refusals or ['все условия доставки выполнены']})
        if not agrees:
            wrong.append(name)
    allows = sum(1 for r in rows if r['shadow_decision'] == WOULD_ALLOW)
    return {
        'schema': 'bridge_shadow_discriminating/1',
        'measured_at': now.isoformat(),
        'events': len(rows),
        'would_allow': allows,
        'would_block': len(rows) - allows,
        'rows': rows,
        'disagreements': wrong,
        'verdict': 'DISCRIMINATES' if not wrong and allows else 'DOES_NOT_DISCRIMINATE',
        'note': ('различение измерено: есть события, которые гейт ПУСКАЕТ, и по одному '
                 'событию на каждое условие, которое он закрывает. Без допусков «все '
                 'заблокированы» было бы неотличимо от постоянного отказа'),
    }
