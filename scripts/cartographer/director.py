#!/usr/bin/env python3
"""Центр директора (Director OS Phase 6) — что владельцу нужно знать и решить сейчас.

READ-ONLY, OFFLINE, БЕЗ СОБСТВЕННОЙ ЛОГИКИ ИСТИНЫ. Модуль не наблюдает машину и не читает
ни карточек, ни git: он берёт УЖЕ ДОКАЗАННЫЕ состояния из принятых производных слоёв —
снимка работы (Phase 5), снимка надёжности (Phase 4), карты авторитетности (Phase 3) — и
отбирает из них то немногое, что требует внимания владельца.

ЧТО ЭТО ЗНАЧИТ НА ПРАКТИКЕ:

* ни одно поле здесь не вычисляется заново. Если нижний слой сказал «не измерено», центр
  повторит «не измерено», а не подставит значение;
* порядок только по доказуемому: severity, ожидание владельца, блокер, свежесть,
  активность. Никакого ранжирования «по важности»;
* **общего балла здоровья НЕТ намеренно**. Сводить расхождение доставки, просроченный
  сторож и незакрытую приёмку в одно число значит потерять ровно ту разницу, ради которой
  все предыдущие фазы и писались;
* на первом экране не больше пяти записей в блоке. Счётчик показывает полное число, а
  «показать все» ведёт в уже существующий раздел портала — второго списка не заводится.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import diff as diff_mod  # noqa: E402
import reliability as reliability_mod  # noqa: E402
import work as work_mod  # noqa: E402

SCHEMA = 'cartographer.director_center/0.1'

TOP_N = 5

SYSTEM_STATES = ('НОРМАЛЬНО', 'ТРЕБУЕТ ВНИМАНИЯ', 'НЕ ИЗМЕРЕНО')

SYSTEM_STATE_DEFINITIONS = {
    'НОРМАЛЬНО': 'все три слоя прочитаны И ни один из них не назвал ничего требующим '
                 'внимания сейчас',
    'ТРЕБУЕТ ВНИМАНИЯ': 'хотя бы один слой назвал подтверждённую запись, требующую '
                        'внимания: решение владельца, подтверждённый сбой или блокер',
    'НЕ ИЗМЕРЕНО': 'хотя бы один из слоёв не прочитан — молчание слоя не является '
                   '«всё хорошо»',
}

BLOCK_LINKS = {
    'owner_decisions': ('#work', '8. Разработка и работа'),
    'attention_now': ('#reliability', '7. Надёжность и проблемы'),
    'current_work': ('#work', '8. Разработка и работа'),
    'blocked': ('#work', '8. Разработка и работа'),
    # Приёмка расщеплена НА ДВА показателя, и это не косметика: «правило применимо, а
    # подтверждения нет» — это проблема, а «применимо ли правило вообще, не измерено» —
    # это незнание. Сложить их значило бы записать в долги 871 запись KANBAN, на которую
    # ни одно правило приёмки не смотрит. NOT_APPLICABLE не считается вовсе.
    'acceptance_attention': ('#work', '8. Разработка и работа'),
    'acceptance_not_measured': ('#work', '8. Разработка и работа'),
    'system_drift': ('#authority', '6. Источник правды и расхождения'),
    # Неподтверждённое состояние — НЕ расхождение. Расхождение это структурное свойство
    # (лишний код в проде, не объявленная каноничность), а «источник не подтверждает» —
    # свойство наблюдения. Смешать их значит обвинить систему в том, чего не измеряли.
    'unverified_state': ('#reliability', '7. Надёжность и проблемы'),
}


class DirectorInputError(Exception):
    """Вход не соответствует контракту. Отказ, а не молчаливая догадка."""


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _load(path, name, validator, error_type):
    """(документ, запись о слое). Непрочитанный слой — отдельный исход, не пустота."""
    if not path:
        return None, {'layer': name, 'path': '—', 'status': 'NOT_GIVEN',
                      'note': 'слой не передан: его часть экрана НЕ измерена'}
    p = Path(path)
    p = p if p.is_file() else p / name
    doc, state = reliability_mod._read_json(p)
    if state != 'READ':
        return None, {'layer': name, 'path': str(p), 'status': state,
                      'note': 'слой не прочитан — это НЕ «там ничего нет»'}
    try:
        validator(doc, str(p))
    except error_type as exc:
        raise DirectorInputError(f'{name}: {exc}')
    return doc, {'layer': name, 'path': str(p), 'status': 'READ',
                 'schema': doc.get('schema_version'),
                 'generated_at': doc.get('generated_at'),
                 'digest': doc.get('semantic_digest')}


def _authority_ok(doc, where):
    if doc.get('schema_version') != 'cartographer.authority_map/0.1':
        raise DirectorInputError(f'{where}: схема {doc.get("schema_version")!r}')


def _item(kind, title, *, detail, source_layer, evidence, sort_key, entity=None,
          anchor=None):
    """Строка центра. `evidence` обязательна: без неё строке здесь не место."""
    if not evidence:
        raise DirectorInputError(f'{kind}/{title}: строка без улики')
    return {'kind': kind, 'title': title, 'entity': entity, 'detail': detail,
            'source_layer': source_layer, 'evidence': evidence, 'anchor': anchor,
            'sort_key': sort_key}


def _block(name, items, total, *, empty, why_ordered):
    anchor, label = BLOCK_LINKS[name]
    return {
        'block': name,
        'count': total,
        'shown': len(items),
        'items': items,
        'empty_means': empty,
        'ordered_by': why_ordered,
        'show_all_anchor': anchor,
        'show_all_label': label,
        'note': 'показаны не более пяти; полный список — в названном разделе портала, '
                'второго списка не заводится',
    }


def build_director_center(work=None, reliability=None, authority=None, now=None):
    now = now or _now()
    layers = []

    # ── 1. нужно моё решение ────────────────────────────────────────────────
    waiting, waiting_total = [], 0
    if work:
        pending = [w for w in work['work'] if w['owner_view_state'] == 'WAITING_OWNER']
        waiting_total = len(pending)
        pending.sort(key=lambda w: (w.get('last_activity_at') or '', w['work_id']))
        for w in pending[:TOP_N]:
            waiting.append(_item(
                'owner_decision', w['title'], entity=w['work_id'],
                detail=(w.get('owner_decision_needed')
                        or 'карточка не называет, что именно решить — НЕ измерено'),
                source_layer='work_snapshot.json',
                evidence=[{'kind': 'source_state',
                           'detail': f"исходное состояние карточки: {w['source_state']}; "
                                     f"{w['mapping_reason']}"}],
                sort_key=w.get('last_activity_at') or '', anchor='#work'))

    # ── 2. требует внимания сейчас ──────────────────────────────────────────
    attention, attention_total = [], 0
    if reliability:
        rank = {'CRITICAL': 0, 'WARNING': 1}
        confirmed = [f for f in reliability['findings']
                     if f['status'] == 'ACTIVE_CONFIRMED' and f['severity'] in rank]
        attention_total = len(confirmed)
        confirmed.sort(key=lambda f: (rank[f['severity']],
                                      -(f.get('occurrence_count') or 0), f['finding_id']))
        for f in confirmed[:TOP_N]:
            attention.append(_item(
                'reliability_finding', f['title'], entity=f['affected_entity'],
                detail=f['classification_reason'], source_layer='reliability_snapshot.json',
                evidence=[{'kind': 'confirmed_now',
                           'detail': f"{f['severity']} · {f['classification']} · "
                                     f"свежесть источника {f['freshness']}: "
                                     f"{f['freshness_rule']}"}],
                sort_key=f"{rank[f['severity']]}{f['finding_id']}", anchor='#reliability'))

    # ── 3. сейчас строится ──────────────────────────────────────────────────
    building, building_total = [], 0
    if work:
        live = [w for w in work['work'] if w['owner_view_state'] == 'IN_PROGRESS']
        building_total = len(live)
        live.sort(key=lambda w: (w.get('last_activity_at') or '', w['work_id']),
                  reverse=True)
        for w in live[:TOP_N]:
            who = (f"{w['claimed_by']} ({w['claim_kind']})" if w.get('claimed_by')
                   else 'исполнитель НЕ измерен')
            building.append(_item(
                'work_item', w['title'], entity=w['work_id'],
                detail=who, source_layer='work_snapshot.json',
                evidence=[{'kind': 'activity',
                           'detail': f"последняя активность "
                                     f"{w.get('last_activity_at') or 'не измерена'}; "
                                     f"состояние {w['source_state']}"}],
                sort_key=w.get('last_activity_at') or '', anchor='#work'))

    # ── 4. заблокировано ────────────────────────────────────────────────────
    blocked, blocked_total = [], 0
    if work:
        stuck = [w for w in work['work'] if w['blocker_status'] == 'BLOCKED']
        blocked_total = len(stuck)
        stuck.sort(key=lambda w: (w.get('last_activity_at') or '', w['work_id']))
        for w in stuck[:TOP_N]:
            blocked.append(_item(
                'blocked_work', w['title'], entity=w['work_id'],
                detail=w['blocker_evidence'][0]['detail'] if w['blocker_evidence'] else '',
                source_layer='work_snapshot.json',
                evidence=w['blocker_evidence'] or [{'kind': 'none', 'detail': '—'}],
                sort_key=w.get('last_activity_at') or '', anchor='#work'))

    # ── 5. приёмка: ДВА разных показателя ───────────────────────────────────
    acceptance = {'unconfirmed': 0, 'unknown': 0, 'conflict': 0, 'not_applicable': 0,
                  'requires_attention': 0, 'not_measured': 0, 'examples': []}
    if work:
        c = work['counts']
        acceptance['unconfirmed'] = c['done_acceptance_unconfirmed']
        acceptance['unknown'] = c['done_acceptance_unknown']
        acceptance['conflict'] = c['acceptance_state_conflicts']
        acceptance['not_applicable'] = c['done_acceptance_not_applicable']
        # ПРОБЛЕМА: правило применимо, а подтверждения нет — плюс расхождение источников
        acceptance['requires_attention'] = (c['done_acceptance_unconfirmed']
                                            + c['acceptance_state_conflicts'])
        # НЕЗНАНИЕ: применимо ли правило — не измерено. Это не долг и не нарушение
        acceptance['not_measured'] = c['done_acceptance_unknown']
        conflicts = [w for w in work['work'] if w.get('acceptance_state_conflict')]
        conflicts.sort(key=lambda w: (w.get('last_activity_at') or '', w['work_id']),
                       reverse=True)
        for w in conflicts[:TOP_N]:
            acceptance['examples'].append(_item(
                'acceptance_conflict', w['title'], entity=w['work_id'],
                detail='приёмка подтверждена, а исходное состояние не закрыто',
                source_layer='work_snapshot.json',
                evidence=[{'kind': 'conflict',
                           'detail': f"состояние {w['source_state']}, приёмка "
                                     f"{w['acceptance_status']} — состояние НЕ переписано"}],
                sort_key=w.get('last_activity_at') or '', anchor='#work'))

    # ── 6. системные расхождения ────────────────────────────────────────────
    drift = {'production_drift': None, 'authority_undefined': None, 'measured': False,
             'items': [],
             'excludes': 'неподтверждённые наблюдения (ACTIVE_UNVERIFIED) сюда НЕ входят: '
                         'расхождение — структурное свойство, а «нечем подтвердить» — '
                         'свойство наблюдения'}
    if authority:
        st = authority['counts']['by_drift_status']
        drift['measured'] = True
        drift['production_drift'] = sum(st.get(k, 0) for k in (
            'MODIFIED', 'MISSING_IN_PRODUCTION', 'EXTRA_IN_PRODUCTION',
            'MISSING_IN_ORIGIN'))
        drift['authority_undefined'] = st.get('AUTHORITY_UNDEFINED', 0)
        drift['by_status'] = dict(st)
        drift['authoritative_commit'] = authority['authoritative_commit'][:12]
        # СОВПАДЕНИЕ РАСХОЖДЕНИЕМ НЕ ЯВЛЯЕТСЯ. Первая редакция показывала здесь топ
        # статусов по численности, и первой строкой шёл IN_SYNC (80 объектов) — то есть
        # блок «системные расхождения» открывался тем, что расхождением не является.
        # Перечисляются только статусы расхождения; «в норме» и производное сюда не
        # попадают вовсе.
        drift_statuses = ('MODIFIED', 'MISSING_IN_PRODUCTION', 'EXTRA_IN_PRODUCTION',
                          'MISSING_IN_ORIGIN', 'DECLARED_NOT_OBSERVED',
                          'OBSERVED_NOT_DECLARED', 'STALE', 'AUTHORITY_UNDEFINED',
                          'UNKNOWN')
        ranked = [(k, v) for k, v in st.items() if k in drift_statuses and v]
        for name, count in sorted(ranked, key=lambda kv: -kv[1])[:TOP_N]:
            drift['items'].append(_item(
                'drift_status', name, detail=f'{count} объект(ов)',
                source_layer='authority_map.json',
                evidence=[{'kind': 'authority_map',
                           'detail': f'карта авторитетности против коммита '
                                     f"{authority['authoritative_commit'][:12]}"}],
                sort_key=f'{count:06d}', anchor='#authority'))
    # ── 6b. состояние не подтверждено — ОТДЕЛЬНЫЙ показатель, не расхождение ──
    unverified_items, unverified_total = [], 0
    if reliability:
        rank = {'CRITICAL': 0, 'WARNING': 1, 'INFO': 2, 'UNKNOWN': 3}
        unver = [f for f in reliability['findings']
                 if f['status'] == 'ACTIVE_UNVERIFIED']
        unverified_total = len(unver)
        unver.sort(key=lambda f: (rank.get(f['severity'], 3), f['finding_id']))
        for f in unver[:TOP_N]:
            unverified_items.append(_item(
                'unverified_finding', f['title'], entity=f['affected_entity'],
                detail='источник запись не отзывал, но подтвердить её «сейчас» нечем',
                source_layer='reliability_snapshot.json',
                evidence=[{'kind': 'freshness',
                           'detail': f"{f['severity']} · свежесть источника "
                                     f"{f['freshness']}: {f['freshness_rule']}"}],
                sort_key=f"{rank.get(f['severity'], 3)}{f['finding_id']}",
                anchor='#reliability'))

    # ── 7. состояние системы, простым языком и без балла ────────────────────
    missing = [rec['layer'] for rec in layers if rec['status'] != 'READ']
    return_layers = layers
    state, state_reason = _system_state(work, reliability, authority,
                                        waiting_total, attention_total, blocked_total)

    center = {
        'schema_version': SCHEMA,
        'generated_at': now.isoformat(),
        'derived_state': True,
        'is_not_a_source_of_truth':
            'центр директора не вычисляет состояний: он отбирает уже доказанные записи '
            'нижних слоёв и ссылается на разделы, где они живут целиком',
        'computes_new_truth': False,
        'has_health_score': False,
        'health_score_note':
            'общего балла здоровья нет намеренно: расхождение доставки, просроченный '
            'сторож и незакрытая приёмка — разные риски, и сумма их не описывает',
        'creates_tasks': False,
        'top_n': TOP_N,
        'system_state_definitions': dict(SYSTEM_STATE_DEFINITIONS),
        'system_state': state,
        'system_state_reason': state_reason,
        'layers': return_layers,
        'blocks': {
            'owner_decisions': _block(
                'owner_decisions', waiting, waiting_total,
                empty='карточек, чьё СОСТОЯНИЕ прямо говорит «ждёт владельца», нет. Это '
                      'не значит, что вопросов нет — значит, ни одна карточка их так не '
                      'объявила',
                why_ordered='по последней активности; ранжирования «по важности» нет'),
            'attention_now': _block(
                'attention_now', attention, attention_total,
                empty='подтверждённых свежим источником записей с объявленной severity '
                      'нет. Неподтверждённое лежит в разделе надёжности',
                why_ordered='severity, затем измеренное число наблюдений'),
            'current_work': _block(
                'current_work', building, building_total,
                empty='ни одна работа не помечена идущей',
                why_ordered='по последней активности'),
            'blocked': _block(
                'blocked', blocked, blocked_total,
                empty='заблокированных по улике работ нет; «давно не менялось» блокером '
                      'не считается',
                why_ordered='по последней активности'),
            'acceptance_attention': _block(
                'acceptance_attention', acceptance['examples'],
                acceptance['requires_attention'],
                empty='работ, где приёмка применима и не подтверждена, нет',
                why_ordered='показаны расхождения источников; «применимо, но не '
                            'подтверждено» считается рядом'),
            'acceptance_not_measured': _block(
                'acceptance_not_measured', [], acceptance['not_measured'],
                empty='работ с неизмеренной применимостью приёмки нет',
                why_ordered='показатель информационный: это НЕ долг и НЕ нарушение, а '
                            'отсутствие правила, которое бы сюда смотрело'),
            'system_drift': _block(
                'system_drift', drift['items'],
                (drift['production_drift'] or 0) + (drift['authority_undefined'] or 0),
                empty='карта авторитетности не приложена — расхождения НЕ измерены',
                why_ordered='по числу объектов в статусе; неподтверждённые наблюдения '
                            'сюда НЕ входят'),
            'unverified_state': _block(
                'unverified_state', unverified_items, unverified_total,
                empty='записей, чьё состояние нечем подтвердить, нет',
                why_ordered='severity, затем идентификатор; это НЕ расхождение, а '
                            'отсутствие подтверждения'),
        },
        'acceptance_summary': {k: v for k, v in acceptance.items() if k != 'examples'},
        'system_drift_summary': {k: v for k, v in drift.items() if k != 'items'},
        'unverified_summary': {
            'count': unverified_total,
            'is_not_drift': 'состояние не подтверждено — это отсутствие подтверждения, а '
                            'не расхождение; в системные расхождения не считается'},
    }
    center['semantic_digest'] = semantic_digest(center)
    return center


def _system_state(work, reliability, authority, waiting, attention, blocked):
    """Состояние системы словами. Балла нет — есть три различимых исхода."""
    missing = [name for name, doc in (('work_snapshot.json', work),
                                      ('reliability_snapshot.json', reliability),
                                      ('authority_map.json', authority)) if not doc]
    if missing:
        return 'НЕ ИЗМЕРЕНО', (f'не прочитаны слои: {", ".join(missing)}. Молчание слоя '
                               'не является «всё хорошо»')
    if attention or waiting or blocked:
        return 'ТРЕБУЕТ ВНИМАНИЯ', (
            f'подтверждённых записей, требующих внимания: {attention}; решений владельца: '
            f'{waiting}; заблокированных работ: {blocked}')
    return 'НОРМАЛЬНО', ('все три слоя прочитаны, и ни один не назвал подтверждённой '
                         'записи, требующей внимания сейчас')


def semantic_view(center):
    return {k: v for k, v in center.items()
            if k not in ('generated_at', 'semantic_digest', 'layers')}


def semantic_digest(center):
    payload = json.dumps(semantic_view(center), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]


def validate_director_center(center, where):
    def need(cond, message):
        if not cond:
            raise DirectorInputError(f'{where}: {message}')

    need(isinstance(center, dict), 'центр не является объектом')
    need(center.get('schema_version') == SCHEMA,
         f"схема {center.get('schema_version')!r}, ожидалась {SCHEMA!r}")
    for key in ('generated_at', 'blocks', 'layers', 'system_state',
                'system_state_reason', 'system_state_definitions',
                'acceptance_summary', 'system_drift_summary'):
        need(key in center, f'поле {key} отсутствует')
    need(center.get('computes_new_truth') is False, 'computes_new_truth обязан быть False')
    need(center.get('has_health_score') is False, 'общий балл здоровья запрещён')
    need(center.get('creates_tasks') is False, 'creates_tasks обязан быть False')
    need(center['system_state'] in SYSTEM_STATES,
         f"состояние {center['system_state']!r} вне словаря")
    need(bool(center['system_state_reason']), 'состояние системы без причины')
    for name, block in center['blocks'].items():
        need(name in BLOCK_LINKS, f'блок {name} не объявлен')
        need(block['shown'] <= center['top_n'],
             f'блок {name}: на первом экране больше {center["top_n"]} записей')
        need(block['shown'] <= block['count'],
             f'блок {name}: показано больше, чем есть')
        need(bool(block['empty_means']), f'блок {name}: пустота без объяснения')
        need(bool(block['ordered_by']), f'блок {name}: порядок без объяснения')
        need(block['show_all_anchor'].startswith('#'),
             f'блок {name}: «показать все» ведёт не в раздел портала')
        for item in block['items']:
            need(bool(item.get('evidence')), f'блок {name}: строка без улики')
            need(bool(item.get('source_layer')), f'блок {name}: строка без названного слоя')
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--work', type=Path, help='снимок работы (Phase 5)')
    ap.add_argument('--reliability', type=Path, help='снимок надёжности (Phase 4)')
    ap.add_argument('--authority', type=Path, help='карта авторитетности (Phase 3)')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)

    final = Path(args.output)
    if final.exists():
        raise SystemExit(f'{final} уже существует; каждый прогон пишет новый каталог')

    layers = []
    try:
        work, rec = _load(args.work, 'work_snapshot.json',
                          work_mod.validate_work_snapshot, work_mod.WorkInputError)
        layers.append(rec)
        rel, rec = _load(args.reliability, 'reliability_snapshot.json',
                         reliability_mod.validate_reliability_snapshot,
                         reliability_mod.ReliabilityInputError)
        layers.append(rec)
        auth, rec = _load(args.authority, 'authority_map.json', _authority_ok,
                          DirectorInputError)
        layers.append(rec)
        center = build_director_center(work, rel, auth)
        center['layers'] = layers
        center['system_state'], center['system_state_reason'] = _system_state(
            work, rel, auth,
            center['blocks']['owner_decisions']['count'],
            center['blocks']['attention_now']['count'],
            center['blocks']['blocked']['count'])
        center['semantic_digest'] = semantic_digest(center)
        validate_director_center(center, 'freshly built')
    except DirectorInputError as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\nЦентр не построен. Это НЕ '
                         '«всё спокойно».')

    protected = [p for p in (args.work, args.reliability, args.authority) if p]
    diff_mod.validate_output(final, [Path(p) for p in protected])

    staging = final.with_name(final.name + '.incomplete')
    if staging.exists():
        raise SystemExit(f'{staging} остался от прерванного прогона; отодвиньте его')
    staging.mkdir(parents=True, mode=0o700)
    p = staging / 'director_center.json'
    with p.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(center, indent=2, ensure_ascii=False) + '\n')
    p.chmod(0o600)
    os.rename(staging, final)

    b = center['blocks']
    print(f"Состояние системы: {center['system_state']} — {center['system_state_reason']}")
    print(f"Нужно решение владельца: {b['owner_decisions']['count']} · требует внимания "
          f"сейчас: {b['attention_now']['count']} · строится: "
          f"{b['current_work']['count']} · заблокировано: {b['blocked']['count']}")
    a = center['acceptance_summary']
    print(f"Приёмка ТРЕБУЕТ ВНИМАНИЯ: {a['requires_attention']} "
          f"(не подтверждена {a['unconfirmed']} + расхождений {a['conflict']}) · "
          f"статус НЕ измерен: {a['not_measured']} · правило не относится: "
          f"{a['not_applicable']}")
    d = center['system_drift_summary']
    print(f"Системные расхождения: доставка {d['production_drift']} · каноничность не "
          f"объявлена {d['authority_undefined']}")
    print(f"Состояние не подтверждено (НЕ расхождение): "
          f"{center['unverified_summary']['count']}")
    print(f"Центр → {final / 'director_center.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
