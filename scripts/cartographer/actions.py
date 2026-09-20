#!/usr/bin/env python3
"""Действия и границы (Director OS Phase 9) — что Director OS вправе дать нажать.

READ-ONLY АУДИТ. Кнопок этот модуль не создаёт: он проверяет, есть ли у существующего
детерминированного контура ВСЁ, что нужно, чтобы действие можно было предложить владельцу.

Правило простое и жёсткое: Director OS не заводит собственный исполнитель. Действие
попадает в UI только если в репозитории УЖЕ есть канонический исполнитель, объявленное
разрешение, проверка входа, запись в аудит, понятное поведение при отказе, идемпотентность
и откат. Нет хотя бы одного свойства — `NOT_READY_FOR_UI`, и это нормальный исход: ноль
готовых действий означает, что Director OS v1 выходит полностью read-only.

КРАСНАЯ ЗОНА не обсуждается и в UI не попадает ни при каких свойствах: движение капитала,
сделки, ввод-вывод средств, аллокация, ставки, лимиты риска, RiskPolicy, стоп-кран,
продвижение на реальные деньги, ротация секретов, удаление прод-файлов, откат origin и
восстановление из копии.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import diff as diff_mod  # noqa: E402
import reliability as reliability_mod  # noqa: E402

SCHEMA = 'cartographer.action_authority_audit/0.1'

VERDICTS = ('READY_FOR_UI', 'NOT_READY_FOR_UI', 'RED_ZONE')

# Свойства, без которых действие в UI не попадает. Список — не вкус: каждое отвечает на
# вопрос, который иначе пришлось бы решать самому Director OS, а он этого делать не вправе.
REQUIRED_PROPERTIES = ('canonical_executor', 'permission_zone', 'validation',
                       'audit_record', 'failure_behaviour', 'idempotent', 'rollback')

PROPERTY_DEFINITIONS = {
    'canonical_executor': 'существующий исполнитель в репозитории (Director OS своего не '
                          'заводит)',
    'permission_zone': 'зона разрешения объявлена правилом',
    'validation': 'исполнитель проверяет вход и отказывает при нарушении',
    'audit_record': 'исполнение попадает в существующий журнал аудита',
    'failure_behaviour': 'поведение при отказе объявлено',
    'idempotent': 'повторный вызов не ломает состояние',
    'rollback': 'откат последствия описан и возможен',
}

# Запрещено в v1 независимо от свойств. Отдельное будущее решение владельца — отдельный
# разговор; здесь эти действия просто не существуют как кнопки.
RED_ZONE = (
    'move_capital', 'execute_trade', 'deposit_withdraw', 'change_allocation',
    'change_rates', 'change_risk_limits', 'change_risk_policy', 'kill_switch',
    'promote_to_real_capital', 'rotate_secrets', 'delete_production_files',
    'rollback_origin', 'restore_backup',
)

RED_ZONE_RU = {
    'move_capital': 'движение капитала', 'execute_trade': 'исполнение сделки',
    'deposit_withdraw': 'ввод и вывод средств', 'change_allocation': 'смена аллокации',
    'change_rates': 'смена ставок', 'change_risk_limits': 'смена лимитов риска',
    'change_risk_policy': 'смена RiskPolicy', 'kill_switch': 'включение или отключение '
                                                            'стоп-крана',
    'promote_to_real_capital': 'перевод на реальные деньги',
    'rotate_secrets': 'ротация секретов',
    'delete_production_files': 'удаление файлов прода',
    'rollback_origin': 'откат origin', 'restore_backup': 'восстановление из копии',
}

# Кандидаты — существующие команды репозитория. Найдены чтением кода, а не выдуманы.
CANDIDATES = (
    {'action': 'card_set_status',
     'title': 'Перевести карточку в другой статус',
     'executor': 'scripts/orchestrator_queue.py set-status',
     'input': 'путь карточки + новый статус',
     'used_by': 'сессии оркестратора и приём заданий'},
    {'action': 'card_attach_probe',
     'title': 'Объявить машинную пробу приёмки у карточки',
     'executor': 'scripts/orchestrator_queue.py probe',
     'input': 'путь карточки + имя пробы из реестра',
     'used_by': 'сессия, берущая карточку в работу'},
    {'action': 'card_claim',
     'title': 'Занять карточку за сессией',
     'executor': 'scripts/check_card_claim.py claim',
     'input': 'путь карточки + идентификатор сессии',
     'used_by': 'сессии перед взятием карточки'},
    {'action': 'card_create',
     'title': 'Создать карточку задания',
     'executor': 'scripts/orchestrator_queue.py create',
     'input': 'заголовок и тело',
     'used_by': 'приём заданий из Telegram и Obsidian'},
    {'action': 'notify_owner_card',
     'title': 'Отправить владельцу карточку в Telegram',
     'executor': 'scripts/orchestrator_queue.py notify',
     'input': 'путь карточки',
     'used_by': 'очередь решений владельца'},
)


class ActionAuditError(Exception):
    """Вход не соответствует контракту. Отказ, а не молчаливая догадка."""


def _now():
    return dt.datetime.now(dt.timezone.utc)


def redact(text):
    return reliability_mod.redact(text)


def _evidence(kind, detail, where=None):
    return {'kind': kind, 'detail': redact(str(detail)[:600]), 'where': where}


def _measure(source, production):
    """Свойства исполнителя — по ТЕКСТУ исполнителя, а не по его названию."""
    path = Path(production) / source.split()[0]
    if not path.is_file():
        return None, path
    text = path.read_text(encoding='utf-8', errors='replace')
    return {
        'canonical_executor': True,
        'validation': bool(re.search(r'REFUSED|raise SystemExit|FORBIDDEN', text)),
        'audit_record': bool(re.search(r'audit_chain|audit_trail_signer|append_entry',
                                       text)),
        'failure_behaviour': bool(re.search(r'REFUSED|exit\(\s*[1-9]|SystemExit', text)),
        'idempotent': bool(re.search(r'idempot|идемпотент', text, re.I)),
        'rollback': bool(re.search(r'\brollback\b|откат[а-я]*\b', text, re.I)),
    }, path


def audit_actions(production, governance=None, now=None):
    now = now or _now()
    production = Path(production)
    zones = {}
    if isinstance(governance, dict):
        for item in governance.get('items') or []:
            if item.get('permission_zone') not in (None, 'UNKNOWN'):
                zones[item.get('governance_id')] = item['permission_zone']
    actions = []
    for cand in CANDIDATES:
        measured, path = _measure(cand['executor'], production)
        ev = [_evidence('executor', cand['executor'], str(path))]
        if measured is None:
            props = {k: None for k in REQUIRED_PROPERTIES}
            verdict, reason = 'NOT_READY_FOR_UI', (
                f"исполнитель {cand['executor']} в дереве не найден — свойства НЕ измерены")
        else:
            props = dict(measured)
            # Зона разрешения берётся у правила, а не назначается здесь.
            props['permission_zone'] = ('AGENT_DECIDES' if zones else None)
            missing = [k for k in REQUIRED_PROPERTIES if not props.get(k)]
            if missing:
                verdict = 'NOT_READY_FOR_UI'
                reason = ('не хватает свойств: ' + ', '.join(missing)
                          + '. Director OS не вправе восполнить их собой')
            else:
                verdict, reason = 'READY_FOR_UI', 'все обязательные свойства измерены'
            for key, value in measured.items():
                ev.append(_evidence('measured', f'{key} = {value}', str(path)))
        actions.append({
            'action': cand['action'], 'title': cand['title'],
            'canonical_executor': cand['executor'], 'input': cand['input'],
            'currently_used_by': cand['used_by'],
            'properties': props,
            'missing_properties': [k for k in REQUIRED_PROPERTIES if not props.get(k)],
            'destructive': cand['action'] in ('card_create', 'notify_owner_card'),
            'owner_approval_required': 'UNKNOWN',
            'verdict': verdict, 'verdict_reason': reason, 'evidence': ev,
        })
    for name in RED_ZONE:
        actions.append({
            'action': name, 'title': RED_ZONE_RU[name],
            'canonical_executor': None, 'input': None, 'currently_used_by': None,
            'properties': {k: None for k in REQUIRED_PROPERTIES},
            'missing_properties': list(REQUIRED_PROPERTIES),
            'destructive': True, 'owner_approval_required': 'REQUIRED',
            'verdict': 'RED_ZONE',
            'verdict_reason': 'красная зона v1: действие не попадает в UI ни при каких '
                              'свойствах; отдельная будущая архитектура — отдельное '
                              'решение владельца',
            'evidence': [_evidence('red_zone',
                                   'запрещено в Director OS v1 по заказу ARB Phase 9',
                                   'phase 9')],
        })

    counts = {
        'actions': len(actions),
        'candidates': len(CANDIDATES),
        'ready_for_ui': sum(1 for a in actions if a['verdict'] == 'READY_FOR_UI'),
        'not_ready': sum(1 for a in actions if a['verdict'] == 'NOT_READY_FOR_UI'),
        'red_zone': sum(1 for a in actions if a['verdict'] == 'RED_ZONE'),
        'by_missing_property': {
            k: sum(1 for a in actions if a['verdict'] == 'NOT_READY_FOR_UI'
                   and k in a['missing_properties'])
            for k in REQUIRED_PROPERTIES},
    }
    snapshot = {
        'schema_version': SCHEMA,
        'generated_at': now.isoformat(),
        'derived_state': True,
        'creates_actions': False,
        'creates_executor': False,
        'ui_exposes_actions': counts['ready_for_ui'] > 0,
        'production': str(production),
        'required_properties': list(REQUIRED_PROPERTIES),
        'property_definitions': dict(PROPERTY_DEFINITIONS),
        'red_zone': list(RED_ZONE),
        'verdict_vocabulary': list(VERDICTS),
        'counts': counts,
        'actions': actions,
        'limits': [
            'Director OS не создаёт собственный исполнитель: действие берётся только у '
            'существующего детерминированного контура.',
            'Нет хотя бы одного обязательного свойства — действие в UI не попадает. '
            'Ноль готовых действий это допустимый исход, а не дефект.',
            'Красная зона не попадает в UI ни при каких свойствах.',
            'Свойства измерены по тексту исполнителя; отсутствие слова в коде означает '
            '«не объявлено», а не «сделано молча».',
        ],
    }
    snapshot['semantic_digest'] = semantic_digest(snapshot)
    return snapshot


def semantic_view(snapshot):
    return {k: v for k, v in snapshot.items()
            if k not in ('generated_at', 'semantic_digest')}


def semantic_digest(snapshot):
    payload = json.dumps(semantic_view(snapshot), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]


def validate_action_audit(snapshot, where):
    def need(cond, message):
        if not cond:
            raise ActionAuditError(f'{where}: {message}')

    need(isinstance(snapshot, dict), 'аудит не является объектом')
    need(snapshot.get('schema_version') == SCHEMA,
         f"схема {snapshot.get('schema_version')!r}, ожидалась {SCHEMA!r}")
    for key in ('generated_at', 'counts', 'actions', 'red_zone', 'required_properties',
                'property_definitions', 'limits'):
        need(key in snapshot, f'поле {key} отсутствует')
    need(snapshot.get('creates_actions') is False, 'creates_actions обязан быть False')
    need(snapshot.get('creates_executor') is False, 'creates_executor обязан быть False')
    seen = set()
    for i, a in enumerate(snapshot['actions']):
        need(a['verdict'] in VERDICTS, f"actions[{i}] вердикт {a['verdict']!r} вне словаря")
        need(a['action'] not in seen, f"дубль действия {a['action']!r}")
        seen.add(a['action'])
        need(bool(a['evidence']), f'actions[{i}] без улики')
        need(not (a['action'] in RED_ZONE and a['verdict'] != 'RED_ZONE'),
             f"actions[{i}]: действие красной зоны получило вердикт {a['verdict']}")
        need(not (a['verdict'] == 'READY_FOR_UI' and a['missing_properties']),
             f'actions[{i}] объявлено готовым при незакрытых свойствах '
             f'{a["missing_properties"]}')
        need(not (a['verdict'] == 'READY_FOR_UI' and a['action'] in RED_ZONE),
             f'actions[{i}]: красная зона объявлена готовой')
    need(snapshot['counts']['ready_for_ui']
         == sum(1 for a in snapshot['actions'] if a['verdict'] == 'READY_FOR_UI'),
         'счётчик готовых действий не сходится с самими действиями')
    need(snapshot.get('ui_exposes_actions') is (snapshot['counts']['ready_for_ui'] > 0),
         'заявление о кнопках в UI расходится с числом готовых действий')
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--production', type=Path, default=Path.home() / 'Documents/SPA_Claude')
    ap.add_argument('--governance', type=Path, help='снимок управления (Phase 8)')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)

    final = Path(args.output)
    if final.exists():
        raise SystemExit(f'{final} уже существует; каждый прогон пишет новый каталог')
    governance = None
    if args.governance:
        p = Path(args.governance)
        p = p if p.is_file() else p / 'governance_snapshot.json'
        governance, state = reliability_mod._read_json(p)
        if state != 'READ':
            governance = None
    try:
        snapshot = audit_actions(args.production, governance)
        validate_action_audit(snapshot, 'freshly built')
    except ActionAuditError as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\nАудит не построен. Это НЕ '
                         '«действий нет».')

    protected = [Path(args.production)]
    if args.governance:
        protected.append(Path(args.governance))
    diff_mod.validate_output(final, protected)
    staging = final.with_name(final.name + '.incomplete')
    if staging.exists():
        raise SystemExit(f'{staging} остался от прерванного прогона; отодвиньте его')
    staging.mkdir(parents=True, mode=0o700)
    p = staging / 'action_authority_audit.json'
    with p.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(snapshot, indent=2, ensure_ascii=False,
                                allow_nan=False) + '\n')
    p.chmod(0o600)
    os.rename(staging, final)

    c = snapshot['counts']
    print(f"Кандидатов: {c['candidates']} · ГОТОВЫ для UI: {c['ready_for_ui']} · не "
          f"готовы: {c['not_ready']} · красная зона: {c['red_zone']}")
    print(f"Чего не хватает: {c['by_missing_property']}")
    print(f"UI показывает действия: {snapshot['ui_exposes_actions']}")
    print(f"Аудит → {final / 'action_authority_audit.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
