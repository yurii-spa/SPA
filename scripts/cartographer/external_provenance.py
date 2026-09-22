#!/usr/bin/env python3
"""Провенанс ВНЕШНИХ канонических входов кокпита.

Зачем этот модуль существует
============================
Замер 22.09 (v1.3.1): идентичность выпуска Director считалась по коду
(``scripts/cartographer/*.py`` + ``tests/cartographer/*.py``), и этого недостаточно.
``architecture/manifest.json`` **не код**: он генерируется из ЖИВОЙ машины
(``launchctl``, plists) и снабжает кокпит объявленными производителями и
``agents[].produces[].slo_hours`` — то есть питает свежесть по SLO, раздел
«Источник правды и расхождения» и счётчики служб. Прод несёт 96 агентов, кандидат — 98.
Один и тот же код при разных байтах манифеста даёт РАЗНЫЙ владельческий вывод.

Поэтому:

* вносить манифест в население ВЫПУСКА нельзя — это заморозило бы снимок одной машины
  внутри кодового выпуска и продублировало генерируемый артефакт;
* но и утверждать, будто хеш кода опознаёт владельческое состояние, тоже нельзя.

Модуль решает это третьим способом: комплект **связывается** с идентичностью внешнего
входа. Инвариант, который держит тест: *тот же код кода + другие байты манифеста ⇒ другой
``provenance_digest``.*

Три исхода, а не два (инв. #17)
===============================
``available`` · ``available`` и пусто · **``NOT_MEASURED``** с названной причиной.
Отсутствующий или непрочитанный вход НИКОГДА не даёт ни нуля, ни «свежо»: ``stale``
остаётся ``None``, а не ``False``, потому что о возрасте неизмеренного файла сказать нечего.

LLM запрещён. Только stdlib.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'external-input-provenance/1'

#: Внешние канонические входы, за которыми обязан следить провенанс комплекта.
#: Класс — ОБЪЯВЛЕНИЕ, а не догадка по расширению (ср. `.claude/rules/site-numbers.md`).
DECLARED_INPUTS = (
    {'path': 'architecture/manifest.json',
     'input_class': 'CANONICAL_EXTERNAL_INPUT',
     'required': True,
     'slo_hours': 24.0,
     'count_key': 'agents',
     'owner_visible': ('объявленные производители и produces[].slo_hours ⇒ свежесть, '
                       'раздел расхождений, счётчики служб')},
    {'path': 'architecture/health_contracts.json',
     'input_class': 'OPTIONAL_EXTERNAL_INPUT',
     'required': False,
     'slo_hours': None,
     'count_key': 'contracts',
     'owner_visible': 'сегодня НЕТ: функция не проведена (--health-contracts не передаётся)'},
)


def _now(now=None):
    return now or datetime.now(timezone.utc)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _count(doc, key):
    """Сколько записей объявляет вход. Не смог сказать — ``None``, а не ноль."""
    if not isinstance(doc, dict):
        return None
    value = doc.get(key)
    return len(value) if isinstance(value, (list, tuple, dict)) else None


def observe_input(production_root, spec, *, now=None):
    """Один внешний вход. Недоступен ⇒ ``state='NOT_MEASURED'`` с причиной."""
    now = _now(now)
    path = Path(production_root) / spec['path']
    row = {'path': spec['path'], 'input_class': spec['input_class'],
           'required': spec['required'], 'slo_hours': spec['slo_hours'],
           'owner_visible_effect': spec['owner_visible'],
           'release_population_member': False}
    if not path.exists():
        row.update(state='NOT_MEASURED', reason='файла нет в дереве выпуска',
                   available=False, content_sha256=None, size_bytes=None,
                   observed_at=now.isoformat(), age_hours=None, stale=None,
                   entry_count=None)
        return row
    try:
        stat = path.stat()
        sha = _sha256(path)
        doc = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        row.update(state='NOT_MEASURED',
                   reason=f'не прочитан: {type(exc).__name__}',
                   available=True, content_sha256=None, size_bytes=None,
                   observed_at=now.isoformat(), age_hours=None, stale=None,
                   entry_count=None)
        return row
    age_h = max(0.0, (now.timestamp() - stat.st_mtime) / 3600.0)
    slo = spec['slo_hours']
    row.update(state='OBSERVED', reason=None, available=True,
               content_sha256=sha, size_bytes=stat.st_size,
               observed_at=now.isoformat(),
               source_mtime=datetime.fromtimestamp(stat.st_mtime,
                                                   timezone.utc).isoformat(),
               age_hours=round(age_h, 3),
               # порога нет ⇒ о протухании сказать нечего: None, а не False
               stale=(None if slo is None else age_h > slo),
               entry_count=_count(doc, spec['count_key']))
    return row


def build_provenance(production_root, *, now=None, inputs=DECLARED_INPUTS):
    """Провенанс всех объявленных внешних входов + его собственный отпечаток.

    ``provenance_digest`` считается по (путь, класс, sha содержимого, состояние,
    число записей) КАЖДОГО входа. Отметки наблюдения и возраст в отпечаток НЕ входят —
    иначе он менялся бы каждый час на неизменных файлах и перестал бы отвечать на свой
    вопрос («те же ли это внешние входы»).
    """
    rows = [observe_input(production_root, spec, now=now) for spec in inputs]
    basis = [{'path': r['path'], 'input_class': r['input_class'],
              'content_sha256': r['content_sha256'], 'state': r['state'],
              'entry_count': r['entry_count']} for r in rows]
    payload = json.dumps(basis, sort_keys=True, ensure_ascii=False)
    unmeasured = [r['path'] for r in rows if r['state'] == 'NOT_MEASURED']
    required_missing = [r['path'] for r in rows
                        if r['required'] and r['state'] == 'NOT_MEASURED']
    return {
        'schema': SCHEMA,
        'inputs': rows,
        'provenance_digest': hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24],
        'digest_basis': ('путь + класс + sha содержимого + состояние + число записей '
                         'каждого объявленного входа; отметки времени и возраст НЕ входят'),
        'unmeasured': unmeasured,
        'required_missing': required_missing,
        # Комплект остаётся собираемым при отсутствии НЕобязательного входа, но
        # отсутствие обязательного названо отдельным полем, а не утоплено в общем счёте.
        'verdict': ('NOT_MEASURED' if required_missing else 'OBSERVED'),
        'note': ('идентичность кода НЕ опознаёт владельческое состояние: манифест '
                 'генерируется из живой машины и меняет вывод при том же коде'),
    }


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--production', required=True)
    ap.add_argument('--json')
    args = ap.parse_args(argv)
    doc = build_provenance(args.production)
    for r in doc['inputs']:
        print(f"{r['state']:12s} {r['path']:42s} sha={str(r['content_sha256'])[:12]:12s} "
              f"записей={r['entry_count']} возраст={r['age_hours']} ч stale={r['stale']}")
    print(f"\nprovenance_digest = {doc['provenance_digest']} · вердикт {doc['verdict']}")
    if doc['required_missing']:
        print('  ОБЯЗАТЕЛЬНЫЕ ВХОДЫ ОТСУТСТВУЮТ: ' + ', '.join(doc['required_missing']))
    if args.json:
        Path(args.json).write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                                   encoding='utf-8')
    return 0 if doc['verdict'] == 'OBSERVED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
