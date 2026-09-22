#!/usr/bin/env python3
"""Director · Атомарный откат раздачи к предыдущему комплекту.

Почему откат ДВУХСТУПЕНЧАТ, и почему это надо знать заранее
===========================================================
Раздача управляется указателем ``current.json``: сервер держит комплект в памяти и
подменяет его, лишь заметив смену указателя. Поэтому:

* **Ступень 1 — указатель.** Одна операция ``os.replace``, и владелец немедленно видит
  прежнюю страницу. Это и есть откат в смысле «что показано».
* **Ступень 2 — код.** Задание пересборки идёт по расписанию из прод-дерева. Пока код
  там новый, следующая сборка снова поставит новый комплект. Откат указателя **не
  отменяет доставку кода**, и путать эти две ступени опасно: откат выглядел бы
  сработавшим и переставал бы действовать через час.

Обе ступени называются вслух, потому что первая быстрая и неполная, а вторая полная и
медленная.

Что проверяется ПЕРЕД откатом
=============================
Целевой комплект обязан существовать, быть читаемым целиком и содержать все файлы
раздачи. Переставить указатель на полусобранный комплект значило бы заменить одну
поломку другой, и сервер тогда продолжил бы раздавать старую копию из памяти, а
владелец увидел бы расхождение между указателем и страницей.

Ничего не удаляет. Только stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

POINTER = 'current.json'
#: Файлы, без которых комплект не комплект. Список тот же, что у сборки.
REQUIRED = ('index.html', 'manifest.webmanifest', 'icon.svg')
_BUNDLE = re.compile(r'^bundle-(\d{8}T\d{6})(?:-([0-9a-f]{12}))?$')


class RollbackError(Exception):
    pass


def read_pointer(serve_root):
    p = Path(serve_root) / POINTER
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def list_bundles(serve_root):
    """Комплекты, ПРИГОДНЫЕ к откату. Непригодный не скрывается — он назван."""
    root = Path(serve_root)
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.glob('bundle-*'), reverse=True):
        if not d.is_dir():
            continue
        m = _BUNDLE.match(d.name)
        missing = [n for n in REQUIRED if not (d / n).is_file()]
        out.append({
            'directory': d.name,
            'stamp': m.group(1) if m else None,
            'digest': m.group(2) if m else None,
            'complete': not missing,
            'missing': missing,
            'bytes': sum((d / n).stat().st_size for n in REQUIRED
                         if (d / n).is_file()),
        })
    return out


def plan(serve_root, *, target=None):
    """План откатa. Ничего не меняет — только называет, что произойдёт."""
    pointer = read_pointer(serve_root)
    bundles = list_bundles(serve_root)
    current = (pointer or {}).get('directory')
    usable = [b for b in bundles if b['complete'] and b['directory'] != current]
    chosen = None
    if target:
        chosen = next((b for b in bundles if b['directory'] == target), None)
        if chosen is None:
            raise RollbackError(f'целевой комплект не найден: {target}')
        if not chosen['complete']:
            raise RollbackError(f'целевой комплект неполон: не хватает {chosen["missing"]}')
    elif usable:
        chosen = usable[0]
    return {
        'serve_root': str(serve_root),
        'current': current,
        'current_digest': (pointer or {}).get('semantic_digest'),
        'bundles_total': len(bundles),
        'bundles_usable': len(usable),
        'incomplete': [b['directory'] for b in bundles if not b['complete']],
        'target': chosen['directory'] if chosen else None,
        'target_digest': chosen['digest'] if chosen else None,
        'possible': chosen is not None,
        'reason': (None if chosen else
                   'нет ни одного полного комплекта, отличного от текущего'),
        'stage_note': ('это ступень 1 — указатель. Она меняет ТО, ЧТО ПОКАЗАНО, и не '
                       'отменяет доставку кода: следующая сборка по расписанию снова '
                       'поставит новый комплект'),
    }


def rollback(serve_root, *, target=None, now=None, dry_run=True):
    """Откат указателя одной операцией. По умолчанию — вхолостую."""
    p = plan(serve_root, target=target)
    if not p['possible']:
        raise RollbackError(p['reason'])
    if dry_run:
        return {**p, 'performed': False,
                'note': 'вхолостую: указатель не тронут'}
    root = Path(serve_root)
    payload = {'directory': p['target'], 'semantic_digest': p['target_digest'],
               'built_at': (now or datetime.now(timezone.utc)).isoformat(),
               'rolled_back_from': p['current'],
               'rollback_note': 'указатель переставлен откатом; код в прод-дереве не менялся'}
    tmp = root / (POINTER + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    os.chmod(tmp, 0o600)
    os.replace(tmp, root / POINTER)          # одна операция: либо старый, либо новый
    return {**p, 'performed': True, 'pointer': payload}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--serve-root', required=True)
    ap.add_argument('--target', help='имя комплекта; по умолчанию — предыдущий полный')
    ap.add_argument('--perform', action='store_true',
                    help='действительно переставить указатель (иначе вхолостую)')
    args = ap.parse_args(argv)
    try:
        out = rollback(args.serve_root, target=args.target, dry_run=not args.perform)
    except RollbackError as exc:
        raise SystemExit(f'ОТКАТ НЕВОЗМОЖЕН: {exc}')
    print(f"сейчас раздаётся : {out['current']} ({out['current_digest']})")
    print(f"комплектов       : {out['bundles_total']} · пригодных {out['bundles_usable']}")
    if out['incomplete']:
        print(f"НЕПОЛНЫЕ         : {out['incomplete']}")
    print(f"цель откатa      : {out['target']} ({out['target_digest']})")
    print(f"выполнено        : {'ДА' if out['performed'] else 'НЕТ (вхолостую)'}")
    print(f"\n{out['stage_note']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
