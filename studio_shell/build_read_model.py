#!/usr/bin/env python3
"""Studio OS Cockpit — read-model projector (Phase 7 vertical slice).

ЧТО ЭТО. Детерминированный проектор: читает КАНОНИЧЕСКИЕ/ПРОИЗВОДНЫЕ источники Studio OS
и собирает ОДИН производный read_model.json, который потребляют ОБА режима оболочки
(Mission Control и Studio View). Это НЕ источник правды и НЕ второй движок процессов:
он только ЧИТАЕТ и проецирует. У каждой сущности объявлен `source` (провенанс), чтобы
её можно было проследить до канона (ADR-469 §UI-DB-≠-canon, инвариант репо #17).

ГРАНИЦЫ. Только stdlib (инвариант #4). Ничего не пишет в канон. Ни одного sudo, ни
чтения секретов, ни кода кандидата. Отсутствие наблюдения — ОТДЕЛЬНОЕ значение
(freshness=UNKNOWN / present=false), никогда не ноль и не выдумка (инвариант #17).

ВЫВОД. studio_shell/read_model.json (производный, одноразовый, перестраиваемый).
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.path.expanduser('~'))
REPO = Path(__file__).resolve().parents[1]
MISSION_STATE = HOME / 'studio-os-scratch' / 'mission-state' / 'v04'
LEDGER = MISSION_STATE / 'ledger.json'
PROGRESS = MISSION_STATE / 'PROGRESS.json'
OUT = Path(__file__).resolve().parent / 'read_model.json'

# freshness thresholds (seconds)
LIVE_S, RECENT_S = 900, 6 * 3600

# ── нормализация состояний: backend → UI (§24). Одна карта, задокументирована. ──────
STATE_TO_UI = {
    'NEW': 'planned', 'NOT_STARTED': 'planned', 'PLANNING': 'planned',
    'CLAIMED': 'queued', 'CAN_CONTINUE': 'queued', 'WAIT_DEPENDENCY': 'queued',
    'WAIT_RESOURCE': 'queued', 'WAIT_PRIORITY': 'queued', 'STALE_INPUT': 'queued',
    'RUNNING': 'running', 'ACTIVE': 'running',
    'REVIEW': 'review',
    'WAIT_OWNER': 'owner_wait',
    'BLOCKED_POLICY': 'blocked', 'BUDGET_EXHAUSTED': 'blocked',
    'FAILED_RETRYABLE': 'failed', 'FAILED_TERMINAL': 'failed',
    'COMPLETED': 'done', 'CLOSED': 'done',
}
# UI-состояние → зона Studio View (§9). Зона — метафора реального состояния.
UI_TO_ZONE = {
    'planned': 'intake', 'queued': 'intake',
    'running': 'engineering', 'review': 'review',
    'owner_wait': 'owner', 'blocked': 'blocked',
    'failed': 'reliability', 'done': 'memory',
}
UI_STATES = ['planned', 'queued', 'running', 'review', 'owner_wait', 'blocked',
             'failed', 'done']


def _now():
    return datetime.now(timezone.utc)


def _parse_ts(s):
    if not s or not isinstance(s, str):
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%dT%H:%M:%S%z',
                '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S'):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _freshness(ts_str):
    dt = _parse_ts(ts_str)
    if dt is None:
        return {'updated_at': ts_str, 'age_seconds': None, 'freshness': 'UNKNOWN'}
    age = (_now() - dt).total_seconds()
    label = 'LIVE' if age < LIVE_S else 'RECENT' if age < RECENT_S else 'STALE'
    return {'updated_at': ts_str, 'age_seconds': int(age), 'freshness': label}


def _load(path):
    """Прочитать JSON. Возвращает (data|None, meta). Отказ — НАЗВАН, не ноль."""
    p = Path(path)
    if not p.exists():
        return None, {'path': str(p), 'present': False, 'freshness': 'UNKNOWN',
                      'why': 'файл отсутствует'}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except (ValueError, OSError) as exc:
        return None, {'path': str(p), 'present': True, 'freshness': 'UNKNOWN',
                      'why': f'{type(exc).__name__}: {exc}'}
    ts = None
    if isinstance(data, dict):
        for k in ('updated_at', 'generated_at', 'revision_at', 'timestamp',
                  'measured_at'):
            if data.get(k):
                ts = data[k]
                break
    meta = {'path': str(p), 'present': True}
    meta.update(_freshness(ts))
    return data, meta


# ─────────────────────────────────────────────────────────────────────────────
def project_missions_and_work(ledger, ledger_meta):
    missions, work = [], []
    counts = {s: 0 for s in UI_STATES}
    if not isinstance(ledger, dict):
        return missions, work, counts
    md = ledger.get('missions') or {}
    wg = ledger.get('work_graph') or {}
    items = ledger.get('items') or {}
    for mid, m in (md.items() if isinstance(md, dict) else []):
        if not isinstance(m, dict):
            continue
        missions.append({
            'id': mid, 'title': m.get('title') or mid,
            'state': m.get('state'), 'ui_state': STATE_TO_UI.get(m.get('state'), 'planned'),
            'permission_zone': m.get('permission_zone'),
            'priority': m.get('priority'),
            'owner_intent': (m.get('owner_intent') or '')[:280],
            'success_criteria': m.get('success_criteria'),
            'source': f'{LEDGER}#missions.{mid}',
        })
    for key, it in (items.items() if isinstance(items, dict) else []):
        if not isinstance(it, dict):
            continue
        wid = it.get('work_item_id') or key
        node = wg.get(wid) if isinstance(wg, dict) else None
        title = (isinstance(node, dict) and (node.get('title') or node.get('summary'))) \
            or it.get('request_summary') or wid
        state = it.get('state')
        ui = STATE_TO_UI.get(state, 'planned')
        counts[ui] = counts.get(ui, 0) + 1
        hist = it.get('history')
        work.append({
            'id': wid, 'work_item_id': wid, 'mission_id': it.get('mission_id'),
            'title': str(title)[:160], 'state': state, 'ui_state': ui,
            'zone': UI_TO_ZONE.get(ui, 'intake'),
            'reason_code': it.get('reason_code'),
            'request_summary': (it.get('request_summary') or '')[:280],
            'created_at': it.get('created_at'),
            'last_transition': it.get('last_transition'),
            'history_len': len(hist) if isinstance(hist, list) else None,
            'attempt': it.get('attempt'),
            'permission_zone': next((m['permission_zone'] for m in missions
                                     if m['id'] == it.get('mission_id')), None),
            'source': f'{LEDGER}#items.{key}',
        })
    return missions, work, counts


def project_activity(ledger):
    """Лента событий из history рабочих элементов + reviews + action_intents.

    Человекочитаемо, а не сырой лог (§8). Ограничено 40 последними.
    """
    events = []
    if not isinstance(ledger, dict):
        return events
    for key, it in (ledger.get('items') or {}).items():
        if not isinstance(it, dict):
            continue
        wid = it.get('work_item_id') or key
        for h in (it.get('history') or []):
            if isinstance(h, dict):
                ts = h.get('at') or h.get('ts') or h.get('when')
                to = h.get('to') or h.get('state') or h.get('to_state')
                rc = h.get('reason_code') or h.get('reason') or ''
                events.append({'ts': ts, 'kind': 'transition',
                               'text': f'{wid} → {to}' + (f' ({rc})' if rc else ''),
                               'ref': wid})
    for rid, r in (ledger.get('reviews') or {}).items():
        if isinstance(r, dict):
            events.append({'ts': r.get('at') or r.get('created_at'), 'kind': 'review',
                           'text': f'review {rid}: {r.get("verdict") or r.get("outcome") or "?"}',
                           'ref': rid})
    dated = [e for e in events if _parse_ts(e.get('ts'))]
    dated.sort(key=lambda e: _parse_ts(e['ts']), reverse=True)
    return dated[:40]


def project_decisions():
    """Owner-решения из авто-индекса трекера (needs-owner). Провенанс → карточки."""
    board = REPO / 'nimbalyst-local' / 'tracker' / '_BOARD.md'
    out = {'items': [], 'source': str(board), 'present': board.exists()}
    if not board.exists():
        out['why'] = 'доска трекера отсутствует'
        return out
    meta = _freshness(None)
    lines = board.read_text(encoding='utf-8', errors='replace').splitlines()
    # частота публикации доски — из строки "Собрана: <ts>"
    for ln in lines[:15]:
        if 'Собрана:' in ln or 'built' in ln.lower():
            import re
            m = re.search(r'(\d{4}-\d{2}-\d{2}T[\d:]+Z)', ln)
            if m:
                meta = _freshness(m.group(1))
    out.update(meta)
    in_section = False
    for ln in lines:
        if 'ЖДЁТ ВЛАДЕЛЬЦА' in ln or 'needs-owner' in ln.lower():
            in_section = True
            continue
        if in_section and ln.startswith('## '):
            break
        if in_section and ln.strip().startswith('- '):
            body = ln.strip()[2:]
            title = body.split('·')[0].strip().strip('*').strip()
            slug = None
            import re
            ms = re.search(r'`(own[a-z-]*-[^`]+)', body)
            if ms:
                slug = ms.group(1)
            out['items'].append({
                'title': title[:200], 'card': slug,
                'zone': 'red', 'permission': 'owner_approval_required',
                'source': f'{board}#needs-owner'
                          + (f' → nimbalyst-local/tracker/{slug}.md' if slug else '')})
    return out


def _tail_json_lines(path, n=1):
    p = Path(path)
    if not p.exists():
        return None, {'path': str(p), 'present': False}
    try:
        lines = [l for l in p.read_text(encoding='utf-8', errors='replace').splitlines()
                 if l.strip()]
    except OSError as exc:
        return None, {'path': str(p), 'present': True, 'why': str(exc)}
    parsed = None
    for l in reversed(lines[-n:] or lines):
        try:
            parsed = json.loads(l)
            break
        except ValueError:
            continue
    st = p.stat()
    meta = {'path': str(p), 'present': True}
    meta.update(_freshness(datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()))
    return parsed, meta


def project_system(ledger, ledger_meta):
    """Плоскости провайдера/кандидата, dispatch, go-live, здоровье. Приватное — назвать."""
    # dispatch (из ledger — истина каноничная)
    dispatch_reason = ledger.get('mission_dispatch_disabled') if isinstance(ledger, dict) else None
    dispatch = {'open': not bool(dispatch_reason),
                'reason': (str(dispatch_reason)[:400] if dispatch_reason else None),
                'source': f'{LEDGER}#mission_dispatch_disabled'}
    # провайдер/кандидат: только НЕпривилегированные логи; launchctl требует прав → назвать
    prov, prov_meta = _tail_json_lines('/tmp/spa_studio_provider_runner.out.log')
    cand, cand_meta = _tail_json_lines('/tmp/spa_studio_worker_runner.out.log')
    provider = {'last_activity': prov_meta, 'last_outcome': (prov or {}).get('processed'),
                'note': 'Живое состояние службы требует привилегий (launchctl) — '
                        'здесь только последняя активность из /tmp-лога; не измерено иначе',
                'source': '/tmp/spa_studio_provider_runner.out.log'}
    candidate = {'last_activity': cand_meta, 'last_scan': (cand or {}).get('processed'),
                 'note': 'То же: живое состояние — привилегированная проба; лог показывает '
                         'последний скан',
                 'source': '/tmp/spa_studio_worker_runner.out.log'}
    golive, gmeta = _load(REPO / 'data' / 'golive_status.json')
    golive_sec = None
    if isinstance(golive, dict):
        golive_sec = {'ready': golive.get('ready'), 'passed': golive.get('passed'),
                      'total': golive.get('total'),
                      'blockers': golive.get('blockers'),
                      'real_track_days': golive.get('real_track_days'),
                      'freshness': gmeta, 'source': str(REPO / 'data/golive_status.json')}
    alerts, ameta = _load(REPO / 'data' / 'risk_alerts.json')
    health = {'risk_alerts': {'count': (alerts or {}).get('count'),
                              'status': (alerts or {}).get('status'),
                              'freshness': ameta,
                              'source': str(REPO / 'data/risk_alerts.json')}}
    ahealth, ahmeta = _load(REPO / 'data' / 'agent_health.json')
    if isinstance(ahealth, dict):
        health['agents'] = {'overall': ahealth.get('overall_status'),
                            'healthy': ahealth.get('healthy_count'),
                            'warning': ahealth.get('warning_count'),
                            'critical': ahealth.get('critical_count'),
                            'total': ahealth.get('total_agents'),
                            'freshness': ahmeta,
                            'source': str(REPO / 'data/agent_health.json')}
    return {'dispatch': dispatch, 'provider_plane': provider,
            'candidate_plane': candidate, 'golive': golive_sec, 'health': health}


def project_roles():
    """Роли: канонические ai_roles + сводка флота. Реестр может быть УСТАРЕВШИМ — назвать."""
    own, ometa = _load(REPO / 'architecture' / 'studio_os_v03_ownership.json')
    ai_roles = (own or {}).get('ai_roles') or {}
    roles = [{'role': r, 'writes': cfg.get('writes'), 'tools': cfg.get('tools'),
              'config': cfg.get('config'),
              'source': str(REPO / 'architecture/studio_os_v03_ownership.json') + f'#ai_roles.{r}'}
             for r, cfg in ai_roles.items()]
    reg, rmeta = _load(REPO / 'data' / 'agent_registry.json')
    fleet = None
    if isinstance(reg, dict):
        fleet = {'total_loaded': reg.get('total_loaded'),
                 'total_known': reg.get('total_known'),
                 'by_role': reg.get('by_role'),
                 'problem_count': reg.get('problem_count'),
                 'freshness': rmeta,
                 'note': 'Реестр флота — снимок; при устаревании freshness=STALE, '
                         'это исторический флот Investment/monitoring, не Studio-роли',
                 'source': str(REPO / 'data/agent_registry.json')}
    return {'ai_roles': roles, 'fleet': fleet, 'ownership_freshness': ometa}


def project_capacity():
    settings, meta = _load(REPO / 'architecture' / 'owner_settings.json')
    if not isinstance(settings, dict):
        return {'present': False, 'source': str(REPO / 'architecture/owner_settings.json')}
    return {'subscription_plan': settings.get('subscription_plan'),
            'subscription_usd_per_month': settings.get('subscription_usd_per_month'),
            'cost_per_cycle_usd': settings.get('cost_per_cycle_usd'),
            'freshness': meta, 'source': str(REPO / 'architecture/owner_settings.json'),
            'note': 'Активные сессии/слоты флота не измеряются этим срезом — не выдумываем'}


def git_status():
    try:
        r = subprocess.run(['git', '-C', str(REPO), 'status', '--porcelain'],
                           capture_output=True, text=True, timeout=20)
        changed = [l for l in r.stdout.splitlines() if l.strip()]
        head = subprocess.run(['git', '-C', str(REPO), 'rev-parse', '--short', 'HEAD'],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        return {'head': head, 'changed_count': len(changed),
                'untracked': len([l for l in changed if l.startswith('??')]),
                'source': 'git status --porcelain'}
    except (OSError, subprocess.SubprocessError) as exc:
        return {'freshness': 'UNKNOWN', 'why': f'{type(exc).__name__}: {exc}'}


def build():
    ledger, ledger_meta = _load(LEDGER)
    missions, work, counts = project_missions_and_work(ledger, ledger_meta)
    decisions = project_decisions()
    system = project_system(ledger or {}, ledger_meta)
    roles = project_roles()
    activity = project_activity(ledger or {})
    capacity = project_capacity()

    overview = {
        'counts': counts,
        'missions_total': len(missions),
        'work_total': len(work),
        'owner_waiting': counts.get('owner_wait', 0) + len(decisions.get('items', [])),
        'running': counts.get('running', 0),
        'blocked': counts.get('blocked', 0),
        'failed': counts.get('failed', 0),
        'done': counts.get('done', 0),
        'dispatch_open': system['dispatch']['open'],
        'ledger_freshness': ledger_meta,
    }
    model = {
        'schema': 'studio-os/cockpit-read-model/1',
        'generated_at': _now().isoformat(),
        'generator': 'studio_shell/build_read_model.py',
        'canonical_note': 'ПРОИЗВОДНАЯ проекция. Источник правды — файлы/git/ledger. '
                          'У каждой сущности есть `source`. UI не есть память компании.',
        'sources': {
            'ledger': ledger_meta,
            'tracker_board': {'path': str(REPO / 'nimbalyst-local/tracker/_BOARD.md')},
        },
        'freshness_legend': {'LIVE': f'< {LIVE_S//60}m', 'RECENT': f'< {RECENT_S//3600}h',
                             'STALE': f'>= {RECENT_S//3600}h', 'UNKNOWN': 'нет отметки времени'},
        'overview': overview,
        'missions': missions,
        'work': work,
        'roles': roles,
        'decisions': decisions,
        'system': system,
        'activity': activity,
        'capacity': capacity,
        'git': git_status(),
        'ui_state_map': STATE_TO_UI,
        'zone_map': UI_TO_ZONE,
    }
    return model


def main():
    model = build()
    tmp = OUT.with_suffix('.tmp')
    tmp.write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, OUT)
    ov = model['overview']
    print(json.dumps({'wrote': str(OUT), 'missions': model['overview']['missions_total'],
                      'work': ov['work_total'], 'counts': ov['counts'],
                      'decisions': len(model['decisions'].get('items', [])),
                      'dispatch_open': ov['dispatch_open'],
                      'ledger_freshness': ov['ledger_freshness'].get('freshness')},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
