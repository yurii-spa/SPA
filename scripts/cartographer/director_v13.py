#!/usr/bin/env python3
"""Director OS v1.3 · Сборка проекции: улики → факты → безопасный к вебу вид.

Порядок обязателен
==================
1. читаются канонические источники;
2. строятся производные модели (капитал, здоровье служб, мост, конвейер, решения);
3. вычисляется отпечаток СМЫСЛА по набору фактов;
4. вся ветка чистится под закрытый веб;
5. и только потом собирается страница.

Чистка устроена в ДВА рубежа, и это не избыточность
===================================================
Первый рубеж — по именам полей: ключ из списка запрещённых выбрасывается целиком,
независимо от содержимого. Второй — по ФОРМЕ значения: каждая строка, дожившая до
выхода, проходит редактор, а готовая страница ещё раз просматривается на запрещённые
формы. Первый рубеж ловит то, что мы знаем; второй — то, чего не знали, когда писали
первый. Поле, появившееся в источнике завтра, будет отредактировано по форме, даже
если его имя никому не известно.

Только stdlib. LLM запрещён.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import bridge_evidence as BE            # noqa: E402
import build_stages as BS               # noqa: E402
import capital_truth as CT              # noqa: E402
import director_facts as DF             # noqa: E402
import owner_decisions as OD            # noqa: E402
import owner_facts as F                 # noqa: E402
import role_lifecycle as RL             # noqa: E402
import health_contract as HC            # noqa: E402
import history_durability as HD         # noqa: E402
import intake_classifier as IC          # noqa: E402
import service_health as SH             # noqa: E402
import system_rnd as SR                 # noqa: E402
import web_projection as WP             # noqa: E402

SCHEMA = 'director_v13/1'

#: Имена полей, которые не выходят наружу НИКОГДА, на любой глубине. Список объявлен
#: здесь, а не рассыпан по коду, чтобы его можно было прочитать целиком и оспорить.
BLOCKED_KEYS = frozenset({
    'decided_by', 'confirmed_by', 'session_id', 'thread_id', 'input_path',
    'output_path', 'bundle_path', 'signature', 'owner_answered_by', 'owner',
    'database_copy', 'run_dir', 'evidence', 'raw', 'payload', 'token', 'secret',
    'password', 'pid', 'installed_paths', 'declared_program', 'stdout', 'stderr',
})

#: Ключи, значения которых — ПУТИ В РЕПОЗИТОРИИ. Они безопасны (репозиторий публичен),
#: но проходят редактор, чтобы абсолютный путь не проехал под видом относительного.
PATH_KEYS = frozenset({'source', 'artifact', 'evidence_carrier', 'source_field',
                       'currency_basis', 'file', 'path'})

#: Формы, которых на выходе быть не может. Проверяются на ГОТОВОЙ странице.
FORBIDDEN_SHAPES = (
    ('домашний абсолютный путь', re.compile(r'/Users/[A-Za-z0-9_.-]+/')),
    ('идентификатор кошелька', WP._WALLET_SHAPE),
    ('идентификатор счёта', WP._IBAN_SHAPE),
    ('имя секрета', WP._SECRET_NAME),
    ('внутренний адрес', WP._INTERNAL_HOSTPORT),
    ('идентификатор владельца в мессенджере', re.compile(r'\bowner:\d{5,}\b')),
    ('адрес электронной почты', re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')),
)


class SecurityError(Exception):
    pass


def _utcnow():
    return datetime.now(timezone.utc)


def _as_datetime(value):
    """Момент времени из чего угодно разумного.

    Сборка комплекта передаёт отметку СТРОКОЙ, а вся арифметика возраста работает с
    datetime. Тихо подставить «сейчас» вместо переданного момента было бы худшим из
    возможных: возраст данных перестал бы соответствовать тому, что написано в шапке.
    """
    if value is None or isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'не разобрана отметка времени сборки: {value!r}') from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def sanitize(node, stats, *, key=None):
    """Два рубежа сразу: имя поля решает судьбу ключа, форма значения — судьбу строки."""
    if key is not None and str(key).lower() in BLOCKED_KEYS:
        stats['blocked_by_name'] = stats.get('blocked_by_name', 0) + 1
        return None, False
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            value, keep = sanitize(v, stats, key=k)
            if keep:
                out[k] = value
        return out, True
    if isinstance(node, (list, tuple)):
        out = []
        for v in node:
            value, keep = sanitize(v, stats, key=None)
            if keep:
                out.append(value)
        return out, True
    if isinstance(node, str):
        clean = WP.redact_text(node)
        if clean != node:
            stats['redacted_strings'] = stats.get('redacted_strings', 0) + 1
        stats['strings'] = stats.get('strings', 0) + 1
        return clean, True
    return node, True


def assert_page_is_clean(page, where='director_v13'):
    """Последний рубеж: готовая страница просматривается на запрещённые формы.

    Он существует потому, что первый рубеж знает только те имена, которые мы успели
    перечислить. Утечка приходит из поля, о котором никто не думал, — и её ловит форма,
    а не имя.
    """
    found = []
    for name, pattern in FORBIDDEN_SHAPES:
        hit = pattern.search(page)
        if hit:
            found.append(f'{name}: …{hit.group(0)[:12]}…')
    if found:
        raise SecurityError(f'{where}: на странице найдены запрещённые формы: '
                            + '; '.join(found))
    return True


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _classification_coverage(root):
    """Покрытие разбора по предмету: сколько карточек ОТНЕСЕНО правилом, а не подсказкой.

    Считается на живых карточках, а не берётся из отчёта: число, перепечатанное из
    прозы, перестаёт быть замером.
    """
    tracker = Path(root) / 'nimbalyst-local' / 'tracker'
    if not tracker.is_dir():
        return {'state': 'NOT_MEASURED', 'reason': 'каталога карточек нет'}
    import re as _re
    fm = _re.compile(r'^---\n(.*?)\n---', _re.S)
    total = routed = suggested = prose = 0
    for path in sorted(tracker.glob('*.md')):
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        m = fm.match(text)
        if not m:
            continue
        total += 1
        fields = {}
        for line in m.group(1).splitlines():
            if not line.startswith(' ') and ':' in line:
                k, _, v = line.partition(':')
                fields[k.strip()] = v.strip()
        if fields.get(IC.PROSE_KEY):
            prose += 1
        out = IC.classify(fields=fields, body=text[:6000])
        if out['routable']:
            routed += 1
        elif out.get('suggestion'):
            suggested += 1
    return {
        'state': 'MEASURED',
        'cards_total': total,
        'routed_by_rule': routed,
        'routed_pct': round(routed / total * 100, 1) if total else None,
        'suggested_only': suggested,
        'suggested_pct': round(suggested / total * 100, 1) if total else None,
        'prose_scope_declared': prose,
        'routable_confidence': list(IC.ROUTABLE_CONFIDENCE),
        'note': ('направляет только правило с измеренной точностью 100 %; подсказка '
                 'эвристики верна в 6 случаях из 19 и потому отнесением не считается'),
        'prose_note': (f'у {prose} карточек объявлен прозаический скоуп в поле '
                       f'{IC.PROSE_KEY} — он НЕ перезаписывается: половина его смысла '
                       f'в отрицаниях, которые одномерным ярлыком не выразить'),
    }


def collect(*, production_root, bridge_root=None, repositories=(), now=None,
            launchd_dirs=None, ledger_path=None, health_contracts=None,
            log_root='/tmp', reliability_snapshot=None):
    """Все производные модели за один проход. Ничего не запускает и не меняет."""
    now = _as_datetime(now) or _utcnow()
    root = Path(production_root)
    data = root / 'data'

    equity = read_json(data / 'equity_curve_daily.json') or {}
    positions = read_json(data / 'current_positions.json')
    risk_config = read_json(data / 'capital_config.json')
    red_flags = read_json(data / 'red_flags.json')
    allocation = read_json(data / 'allocation_rationale.json')
    manifest = read_json(root / 'architecture' / 'manifest.json') or {}
    registry = read_json(data / 'agent_registry.json') or {}

    history = ({'daily': equity.get('daily') or [],
                'summary': equity.get('summary') or {},
                'mode': equity.get('execution_mode'),
                'observed_at': equity.get('generated_at')} if equity else None)

    capital = DF.build_capital_facts(history=history, positions=positions,
                                     risk_config=risk_config, red_flags=red_flags,
                                     allocation=allocation, now=now)
    # Ряд для графика отдаётся отдельно: он большой, и в набор фактов не входит.
    capital['series_rows'] = [
        {'date': r.get('date'), 'close_equity': r.get('close_equity'),
         'evidenced': bool(r.get('evidenced'))}
        for r in (history or {}).get('daily') or ()]

    dirs = launchd_dirs or [os.path.expanduser('~/Library/LaunchAgents'),
                            str(root / 'launchd')]
    health = SH.build_service_health(
        manifest=manifest, registry=registry, launchctl=SH.read_launchctl(),
        plists=SH.collect_plists(dirs), production_root=str(root), now=now)

    bridge = {'state': 'NOT_MEASURED', 'reason': 'корень моста не подан'}
    if bridge_root and Path(bridge_root).is_dir():
        bridge = BE.build_bridge_evidence(
            db_path=str(Path(bridge_root) / 'state' / 'bridge.db'),
            artifacts_root=str(Path(bridge_root) / 'artifacts'),
            repositories=repositories, now=now)

    pipeline = BS.build_pipeline(cards=BS.read_cards(root / 'nimbalyst-local' / 'tracker'),
                                 bridge=bridge, service_health=health, now=now,
                                 production_root=str(root))
    decisions = OD.build_owner_decisions(
        production_root=str(root),
        bridge_db=(str(Path(bridge_root) / 'state' / 'bridge.db') if bridge_root else None),
        now=now)

    # ── Tier-1: новая правда, появившаяся после v1.3. Отрисовка не меняется —
    #    меняется то, что в ней можно сказать честно.
    durability = ({'state': 'NOT_MEASURED',
                   'reason': 'путь журнала закрытых дней не подан'} if not ledger_path
                  else HD.build_durability(production_root=str(root),
                                           ledger_path=ledger_path, now=now))

    contracts = []
    if health_contracts:
        declared = read_json(health_contracts) or {}
        contracts = declared.get('contracts') or []
    measured_health = (HC.build_health(contracts, production_root=str(root), now=now,
                                       log_root=log_root) if contracts else
                       {'schema': 'health_summary/1', 'declared_contracts': 0,
                        'entities': [], 'counts': {v: 0 for v in HC.VERDICTS},
                        'unhealthy': [], 'blind': [],
                        'coverage_note': 'контрактов здоровья не объявлено'})

    # Находки надёжности читаются из комплекта улик, если он подан. Не подан —
    # повода «повторяющийся отказ» просто нет, и это честнее, чем подставить пустоту.
    rnd = SR.build_system_rnd(service_health=health, bridge=bridge,
                              owner_decisions=decisions, pipeline=pipeline,
                              reliability=(read_json(Path(reliability_snapshot))
                                           if reliability_snapshot else None),
                              now=now)

    classification = _classification_coverage(root)

    # Состояние ролей ВЫВОДИТСЯ. Прежде кокпит утверждал «CIO в рантайме:
    # DOCUMENTED_ONLY», взяв это из литерала тестовой фикстуры; замер показал ACTIVE
    # с девятью читателями, четыре из которых в денежном пути.
    roles = RL.measure_roles(production_root=str(root), launchd_dirs=dirs, now=now)

    facts = list(capital['facts'])
    return {
        'schema': SCHEMA,
        'generated_at': now.isoformat(),
        'capital': capital,
        'service_health': health,
        'measured_health': measured_health,
        'history_durability': durability,
        'system_rnd': rnd,
        'classification': classification,
        'roles': roles,
        'bridge': bridge,
        'pipeline': pipeline,
        'owner_decisions': decisions,
        'facts': facts,
        'fact_count': len(facts),
        'fact_digest': F.semantic_digest(facts),
        'digest_design':
            'отпечаток смысла считается по ОБЪЯВЛЕННОМУ списку смысловых полей набора '
            'фактов. Поле, добавленное завтра, на отпечаток не влияет, пока его не '
            'объявят смысловым явно; отметки наблюдения в список не входят по построению',
    }


def build(*, production_root, bridge_root=None, repositories=(), now=None,
          launchd_dirs=None, ledger_path=None, health_contracts=None,
          log_root='/tmp', reliability_snapshot=None):
    """Проекция, пригодная к публикации в закрытом вебе."""
    raw = collect(production_root=production_root, bridge_root=bridge_root,
                  repositories=repositories, now=now, launchd_dirs=launchd_dirs,
                  ledger_path=ledger_path, health_contracts=health_contracts,
                  log_root=log_root, reliability_snapshot=reliability_snapshot)
    stats = {}
    clean, _ = sanitize(raw, stats)
    clean['sanitize_stats'] = stats
    # Отпечаток берётся с ЧИСТЫХ фактов: публикуется именно этот вид, и отвечать
    # отпечаток обязан за него, а не за то, что осталось локально.
    clean['fact_digest'] = F.semantic_digest(clean.get('facts') or [])
    return clean
