#!/usr/bin/env python3
"""Инвестиции и R&D (Director OS Phase 7) — показать, не посчитать.

READ-ONLY. Director OS **не становится инвестиционным движком**: стратегии, доходность,
риск и распределение капитала остаются за существующими источниками SPA. Здесь не
создаётся ни одной карточки стратегии, не дублируется состояние и не вычисляется ни одной
рекомендации.

ГЛАВНАЯ ГРАНИЦА — РЕЖИМ. REAL, PAPER, SHADOW, FORECAST и R&D никогда не складываются в
одно число. Режим берётся ТОЛЬКО из объявления самого источника; из имени файла он не
выводится никогда.

Отдельно про ловушку, которая живёт прямо в данных: ``is_demo: false`` в этом репозитории
НЕ означает реальных денег. У `current_positions.json` рядом стоит
``execution_mode: read_only_simulation``, а `capital_config.json` объявляет
``capital.mode: paper``. Поэтому «не демо» читается как «не выдуманные цифры», а не как
«живой капитал», и реальный капитал здесь остаётся НЕ ДОКАЗАННЫМ.
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

SCHEMA = 'cartographer.investment_snapshot/0.1'

MODES = ('REAL', 'PAPER', 'SHADOW', 'FORECAST', 'RND', 'UNKNOWN')

MODE_DEFINITIONS = {
    'REAL': 'живой капитал. Ставится ТОЛЬКО если источник объявил исполнение реальным',
    'PAPER': 'бумажная торговля: цифры настоящие, деньги — нет',
    'SHADOW': 'теневой расчёт рядом с основным, капитал не двигает',
    'FORECAST': 'прогноз, а не заработанное',
    'RND': 'исследование: гипотеза, бэктест, лаборатория',
    'UNKNOWN': 'источник режим не объявил — режим НЕ измерен',
}

# Слова, которыми источники ЭТОГО репозитория объявляют режим. Список — перевод
# объявлений, а не догадка: каждое значение встречается в поле source'а.
_MODE_WORDS = {
    'read_only_simulation': 'PAPER', 'paper': 'PAPER', 'paper_trading': 'PAPER',
    'shadow': 'SHADOW', 'decision_shadow': 'SHADOW',
    'forecast': 'FORECAST', 'projection': 'FORECAST',
    'research': 'RND', 'research_only': 'RND', 'backtest': 'RND', 'lab': 'RND',
    'live': 'REAL', 'real': 'REAL', 'execution': 'REAL',
}

LIFECYCLE_SOURCE = 'data/strategy_lab_promotion.json (поле pipeline)'

APPROVAL_STATES = ('APPROVED', 'WAITING', 'NOT_REQUIRED', 'UNKNOWN')

# Типы величин. «Капитал» одним словом здесь запрещён: объявленный стартовый капитал,
# текущая equity, размещённое и кэш — РАЗНЫЕ величины, и складывать их нельзя.
METRIC_TYPES = ('CONFIGURED_CAPITAL', 'CURRENT_EQUITY', 'POSITION_VALUE', 'CASH',
                'ACCRUED_YIELD', 'NET_PNL', 'UNKNOWN')

METRIC_DEFINITIONS = {
    'CONFIGURED_CAPITAL': 'объявленный стартовый капитал — параметр, а не наблюдение',
    'CURRENT_EQUITY': 'текущая equity книги по наблюдению источника',
    'POSITION_VALUE': 'стоимость размещённого',
    'CASH': 'кэш',
    'ACCRUED_YIELD': 'накопленная доходность',
    'NET_PNL': 'чистый результат',
    'UNKNOWN': 'источник не назвал род величины',
}

# Откуда берётся каждая величина: (источник, путь к полю, тип). Ничего не вычисляется —
# только перенос того, что источник НАЗВАЛ своим именем.
CAPITAL_METRIC_MAP = (
    ('capital_config.json', 'capital.starting_capital_usd', 'CONFIGURED_CAPITAL',
     'capital.currency'),
    ('current_positions.json', 'current_equity_usd', 'CURRENT_EQUITY', None),
    ('current_positions.json', 'deployed_usd', 'POSITION_VALUE', None),
    ('current_positions.json', 'cash_usd', 'CASH', None),
    ('current_positions.json', 'accrued_yield_usd', 'ACCRUED_YIELD', None),
    ('current_positions.json', 'net_pnl_usd', 'NET_PNL', None),
)


def capital_metrics(docs, by_name):
    """Величины по ТИПАМ, а не одним словом «капитал». Ничего не суммируется.

    Валюта берётся только из объявленного поля. Суффикс `_usd` в имени поля объявлением
    НЕ является: имя переменной — не единица измерения, и подставлять по нему валюту
    значило бы выдумать её.
    """
    out = []
    for source, field, kind, currency_field in CAPITAL_METRIC_MAP:
        doc = docs.get(source)
        if not isinstance(doc, dict):
            continue
        value = _dig(doc, field)
        if value is None:
            continue
        currency = _dig(doc, currency_field) if currency_field else None
        out.append({
            'metric_type': kind,
            'value': json_safe(value),
            'currency': currency,
            'currency_basis': (f'объявлено полем {currency_field}' if currency else
                               'источник валюту не объявляет; суффикс _usd в имени поля '
                               'объявлением НЕ является — валюта НЕ измерена'),
            'mode': by_name[source]['mode'],
            'source': source,
            'source_field': field,
            'observed_at': by_name[source]['observed_at'],
            'note': METRIC_DEFINITIONS[kind],
        })
    return out


class InvestmentInputError(Exception):
    """Вход не соответствует контракту. Отказ, а не молчаливая догадка."""


SOURCE_CONTRACTS = {
    'capital_config.json': {
        'represents': 'объявленный стартовый капитал, лимиты распределения и параметры '
                      'риска',
        'basis': 'declared', 'mode_field': 'capital.mode',
        'can_prove_capital': True, 'can_prove_performance': False,
        'can_prove_risk': True, 'can_prove_promotion': False, 'can_prove_approval': False,
        'limit': 'это ОБЪЯВЛЕНИЕ параметров, а не наблюдение денег',
    },
    'current_positions.json': {
        'represents': 'состояние книги: капитал, размещено, кэш, накопленная доходность',
        'basis': 'observed', 'mode_field': 'execution_mode',
        'can_prove_capital': True, 'can_prove_performance': True,
        'can_prove_risk': False, 'can_prove_promotion': False, 'can_prove_approval': False,
        'limit': 'execution_mode объявляет режим; is_demo=false режимом НЕ является',
    },
    'equity_curve_daily.json': {
        'represents': 'дневная кривая капитала',
        'basis': 'observed', 'mode_field': 'execution_mode',
        'can_prove_capital': True, 'can_prove_performance': True,
        'can_prove_risk': False, 'can_prove_promotion': False, 'can_prove_approval': False,
        'limit': 'кривая того режима, который объявлен рядом',
    },
    'paper_trading_status.json': {
        'represents': 'статус бумажной торговли: дни, доходность, последний цикл',
        'basis': 'observed', 'mode_field': 'execution_mode',
        'can_prove_capital': True, 'can_prove_performance': True,
        'can_prove_risk': False, 'can_prove_promotion': False, 'can_prove_approval': False,
        'limit': 'бумага; переносить её доходность на реальные деньги нельзя',
    },
    'strategy_configs.json': {
        'represents': 'объявленные конфигурации стратегий',
        'basis': 'declared', 'mode_field': None,
        'can_prove_capital': False, 'can_prove_performance': False,
        'can_prove_risk': False, 'can_prove_promotion': False, 'can_prove_approval': False,
        'limit': 'конфигурация — не работающая стратегия и не капитал',
    },
    'promotion_report.json': {
        'represents': 'решения движка продвижения по стратегиям',
        'basis': 'observed', 'mode_field': None,
        'can_prove_capital': False, 'can_prove_performance': True,
        'can_prove_risk': False, 'can_prove_promotion': True, 'can_prove_approval': False,
        'limit': 'это ПРЕДЛОЖЕНИЕ ИСТОЧНИКА, а не совет Director OS и не решение владельца',
    },
    'strategy_lab_promotion.json': {
        'represents': 'конвейер R&D и стадия каждого рукава',
        'basis': 'derived', 'mode_field': None, 'declares_pipeline': True,
        'can_prove_capital': False, 'can_prove_performance': True,
        'can_prove_risk': True, 'can_prove_promotion': True, 'can_prove_approval': False,
        'limit': 'лаборатория: капитал не двигает; собственный срок годности не объявляет',
    },
    'strategy_lab/portfolio_book.json': {
        'represents': 'книга лаборатории стратегий',
        'basis': 'derived', 'mode_field': None,
        'can_prove_capital': False, 'can_prove_performance': True,
        'can_prove_risk': False, 'can_prove_promotion': False, 'can_prove_approval': False,
        'limit': 'сам файл объявляет is_advisory и research_only',
    },
    'golive_status.json': {
        'represents': 'готовность к выходу на живой капитал по критериям',
        'basis': 'observed', 'mode_field': None,
        'can_prove_capital': False, 'can_prove_performance': False,
        'can_prove_risk': True, 'can_prove_promotion': True, 'can_prove_approval': False,
        'limit': 'готовность — не разрешение: решение о живых деньгах за владельцем',
    },
    'kill_switch_status.json': {
        'represents': 'состояние стоп-крана',
        'basis': 'observed', 'mode_field': None,
        'can_prove_capital': False, 'can_prove_performance': False,
        'can_prove_risk': True, 'can_prove_promotion': False, 'can_prove_approval': False,
        'limit': 'состояние на момент снятия',
    },
    'allocation_rationale.json': {
        'represents': 'обоснование распределения по книге',
        'basis': 'derived', 'mode_field': 'mode',
        'can_prove_capital': True, 'can_prove_performance': False,
        'can_prove_risk': True, 'can_prove_promotion': False, 'can_prove_approval': False,
        'limit': 'режим объявлен полем mode',
    },
}


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _read_json(path):
    return reliability_mod._read_json(path)


def redact(text):
    return reliability_mod.redact(text)


def _evidence(kind, detail, where=None):
    return {'kind': kind, 'detail': redact(str(detail)[:600]), 'where': where}


def json_safe(value):
    """Значение, которое переживёт JSON. Не-конечное число НАЗЫВАЕТСЯ, а не теряется.

    `promotion_report.json` содержит `-Infinity` (три раза на живых данных). Python
    сериализует его дословно, и такой файл уже не является валидным JSON: браузер его не
    читает, а страница молча остаётся без раздела. Подменить на null значило бы стереть
    факт, поэтому значение переезжает строкой рядом с флагом.
    """
    if isinstance(value, float) and (value != value or value in (float('inf'),
                                                                 float('-inf'))):
        return {'non_finite': True, 'as_text': repr(value),
                'note': 'источник записал не-конечное число; оно сохранено как текст, '
                        'потому что JSON такого значения не имеет'}
    return value


def _dig(doc, dotted):
    cur = doc
    for part in dotted.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def declared_mode(doc, field, where):
    """(режим, улика). Только ОБЪЯВЛЕНИЕ источника; из имени файла режим не выводится.

    Отдельно закрыт случай `is_demo`: это поле отвечает на вопрос «выдуманы ли числа», а
    не «настоящие ли деньги». Прочитать `is_demo: false` как REAL значило бы объявить
    живым капитал, которого нет.
    """
    if not isinstance(doc, dict):
        return 'UNKNOWN', _evidence('no_document', 'источник не прочитан', where)
    raw = _dig(doc, field) if field else None
    if raw is None:
        if 'is_demo' in doc:
            return 'UNKNOWN', _evidence(
                'is_demo_is_not_a_mode',
                f"источник объявляет только is_demo={doc['is_demo']}; это НЕ режим: "
                'поле говорит, выдуманы ли числа, а не настоящие ли деньги', where)
        return 'UNKNOWN', _evidence('no_mode_field',
                                    'источник режим не объявляет — режим НЕ измерен', where)
    text = str(raw).strip().lower()
    mode = _MODE_WORDS.get(text)
    if mode is None:
        for word, value in _MODE_WORDS.items():
            if word in text:
                mode = value
                break
    if mode is None:
        return 'UNKNOWN', _evidence('unmapped_mode',
                                    f'источник объявил режим «{raw}», которого нет среди '
                                    'известных объявлений — режим НЕ измерен', where)
    return mode, _evidence('declared_mode', f'{field} = «{raw}»', where)


def _source_record(name, path, status, *, doc=None, now=None):
    c = SOURCE_CONTRACTS.get(name, {})
    mode, mode_ev = ('UNKNOWN', None)
    if status == 'READ' and c.get('mode_field'):
        mode, mode_ev = declared_mode(doc, c['mode_field'], name)
    gen = (doc or {}).get('generated_at') or (doc or {}).get('timestamp') \
        or (doc or {}).get('created_at') if isinstance(doc, dict) else None
    age = reliability_mod._age_hours(gen, now or _now()) if gen else None
    return {
        'source': name, 'path': str(path), 'status': status,
        'represents': c.get('represents'), 'basis': c.get('basis'),
        'mode': mode, 'mode_evidence': mode_ev,
        'mode_field': c.get('mode_field'),
        'can_prove_capital': c.get('can_prove_capital'),
        'can_prove_performance': c.get('can_prove_performance'),
        'can_prove_risk': c.get('can_prove_risk'),
        'can_prove_promotion': c.get('can_prove_promotion'),
        'can_prove_owner_approval': c.get('can_prove_approval'),
        'observed_at': gen, 'age_hours': age,
        'freshness': 'UNKNOWN',
        'freshness_rule': 'собственного срока годности источник не объявляет; возраст '
                          'показан, вердикт не вынесен',
        'limit': c.get('limit'),
    }


def _object(strategy_id, name, mode, *, lifecycle_state, source, evidence,
            id_namespace='unnamespaced',
            source_authority='AUTHORITY_UNDEFINED', capital_value=None,
            capital_currency=None, performance_metrics=(), yield_metrics=(),
            risk_classification=None, risk_limits=(), observed_at=None,
            rnd_status=None, backtest_status=None, canary_status=None,
            promotion_status=None, owner_approval_status='UNKNOWN',
            related_decisions=(), related_work=(), related_findings=(),
            mode_evidence=None):
    """Инвестиционный объект. Неизвестное остаётся пустым — не вычисляется."""
    if mode not in MODES:
        raise InvestmentInputError(f'{strategy_id}: режим {mode!r} вне словаря')
    if not evidence:
        raise InvestmentInputError(f'{strategy_id}: объект без улики')
    return {
        # идентификатор тоже приезжает из чужого файла: если в id окажется форма секрета,
        # она обязана быть вырезана наравне с названием
        'strategy_id': redact(strategy_id),
        # пространство имён: S-идентификаторы конфигураций и имена рукавов лаборатории —
        # РАЗНЫЕ пространства, и совпадение между ними ничего не значило бы
        'id_namespace': id_namespace,
        'sources': [source],
        'facts_by_source': {},
        'conflicting_facts': [],
        'strategy_name': redact(name),
        'mode': mode,
        'mode_evidence': mode_evidence,
        'lifecycle_state': lifecycle_state,
        'capital_value': capital_value,
        'capital_currency': capital_currency,
        'performance_metrics': list(performance_metrics),
        'yield_metrics': list(yield_metrics),
        'risk_classification': risk_classification,
        'risk_limits': list(risk_limits),
        'evidence': list(evidence),
        'source': source,
        'source_authority': source_authority,
        'observed_at': observed_at,
        'freshness': 'UNKNOWN',
        'rnd_status': rnd_status,
        'backtest_status': backtest_status,
        'canary_status': canary_status,
        'promotion_status': promotion_status,
        'owner_approval_status': owner_approval_status,
        'related_decisions': list(related_decisions),
        'related_work': list(related_work),
        'related_findings': list(related_findings),
    }


def build_investment_snapshot(production, now=None):
    now = now or _now()
    production = Path(production)
    data = production / 'data'
    sources, objects = [], []
    docs = {}

    for name in SOURCE_CONTRACTS:
        p = data / name
        doc, state = _read_json(p)
        docs[name] = doc if state == 'READ' else None
        sources.append(_source_record(name, p, state, doc=doc, now=now))

    by_name = {s['source']: s for s in sources}

    # ── капитал по РЕЖИМАМ; реальный капитал не выводится ни из чего ─────────
    capital = {mode: None for mode in MODES}
    capital_evidence = []
    cfg, pos = docs.get('capital_config.json'), docs.get('current_positions.json')
    declared_capital_mode = by_name['capital_config.json']['mode']
    if isinstance(cfg, dict):
        cap = cfg.get('capital') or {}
        if cap.get('starting_capital_usd') is not None:
            capital[declared_capital_mode] = cap['starting_capital_usd']
            capital_evidence.append(_evidence(
                'declared_capital',
                f"capital_config объявляет starting_capital_usd="
                f"{cap['starting_capital_usd']} {cap.get('currency')} при mode="
                f"{cap.get('mode')!r}", 'capital_config.json'))
    pos_mode = by_name['current_positions.json']['mode']
    if isinstance(pos, dict) and pos.get('current_equity_usd') is not None:
        capital[pos_mode] = pos['current_equity_usd']
        capital_evidence.append(_evidence(
            'observed_equity',
            f"current_positions: equity={pos['current_equity_usd']}, "
            f"pnl={pos.get('net_pnl_usd')} при execution_mode="
            f"{pos.get('execution_mode')!r}", 'current_positions.json'))
    real_proven = any(s['mode'] == 'REAL' for s in sources)
    capital_evidence.append(_evidence(
        'real_capital',
        'РЕАЛЬНЫЙ капитал НЕ ДОКАЗАН: ни один источник не объявил режим REAL. '
        'is_demo=false режимом не является'
        if not real_proven else 'источник объявил режим REAL', 'investments'))

    # ── стратегии: объявленные конфигурации ─────────────────────────────────
    configs = docs.get('strategy_configs.json')
    if isinstance(configs, dict):
        for item in (configs.get('configs') or []):
            if not isinstance(item, dict):
                continue
            objects.append(_object(
                str(item.get('id')), str(item.get('id')), 'UNKNOWN',
                id_namespace='strategy_id',
                lifecycle_state='DECLARED_CONFIG', source='strategy_configs.json',
                mode_evidence=_evidence('no_mode',
                                        'конфигурация режима не объявляет',
                                        'strategy_configs.json'),
                evidence=[_evidence('config',
                                    f"valid={item.get('valid')}, "
                                    f"hash={item.get('config_hash')}",
                                    'strategy_configs.json')],
                observed_at=by_name['strategy_configs.json']['observed_at']))

    # ── решения движка продвижения: ПРЕДЛОЖЕНИЕ ИСТОЧНИКА ───────────────────
    promo = docs.get('promotion_report.json')
    if isinstance(promo, dict):
        for dec in (promo.get('decisions') or []):
            if not isinstance(dec, dict):
                continue
            metrics = [{'name': k, 'value': json_safe(v),
                        'source': 'promotion_report.json'}
                       for k, v in (dec.get('metrics') or {}).items()]
            objects.append(_object(
                str(dec.get('strategy_id')), str(dec.get('strategy_id')),
                'UNKNOWN', id_namespace='strategy_id',
                lifecycle_state='PROMOTION_DECISION',
                source='promotion_report.json',
                mode_evidence=_evidence('no_mode',
                                        'движок продвижения режим не объявляет',
                                        'promotion_report.json'),
                performance_metrics=metrics,
                promotion_status=str(dec.get('action') or 'UNKNOWN').upper(),
                evidence=[_evidence(
                    'source_proposal',
                    f"ПРЕДЛОЖЕНИЕ ИСТОЧНИКА: {dec.get('action')} — {dec.get('reason')}. "
                    'Это запись движка, а не совет Director OS и не решение владельца',
                    'promotion_report.json')],
                observed_at=dec.get('ts')))

    # ── R&D: конвейер и стадии берутся у самого источника ───────────────────
    lab = docs.get('strategy_lab_promotion.json')
    pipeline, stage_counts = None, {}
    if isinstance(lab, dict):
        pipeline = lab.get('pipeline')
        stage_counts = lab.get('stage_counts') or {}
        for i, sleeve in enumerate(lab.get('sleeves') or []):
            if not isinstance(sleeve, dict):
                continue
            stage = sleeve.get('stage') or sleeve.get('verdict') or 'UNKNOWN'
            crit = sleeve.get('criteria') or {}
            objects.append(_object(
                str(sleeve.get('id') or sleeve.get('sleeve') or i),
                str(sleeve.get('sleeve') or sleeve.get('name') or sleeve.get('id')
                    or f'рукав {i}'),
                'RND', id_namespace='sleeve_id', lifecycle_state=str(stage),
                source='strategy_lab_promotion.json',
                mode_evidence=_evidence(
                    'lab', 'лаборатория стратегий: исследование, капитал не двигает',
                    'strategy_lab_promotion.json'),
                rnd_status=str(stage),
                backtest_status=('PASS' if sleeve.get('beats_floor') else 'NOT_PASSED'),
                risk_limits=[{'name': k, 'detail': v.get('detail'),
                              'pass': v.get('pass'), 'source': 'strategy_lab_promotion.json'}
                             for k, v in crit.items() if isinstance(v, dict)],
                evidence=[_evidence('pipeline',
                                    f'конвейер источника: {pipeline}; стадии: '
                                    f'{stage_counts}', 'strategy_lab_promotion.json')],
                observed_at=by_name['strategy_lab_promotion.json']['observed_at']))
    raw_objects = list(objects)
    objects, identity = merge_by_stable_id(raw_objects)
    return _finish(production, now, sources, objects, capital, capital_evidence,
                   real_proven, docs, by_name, pipeline, stage_counts,
                   declared_capital_mode, identity, capital_metrics(docs, by_name))


def merge_by_stable_id(objects):
    """Один устойчивый идентификатор — одна стратегия, но факты источников НЕ теряются.

    Правила здесь ровно те, что были измерены: одинаковый stable id в одном пространстве
    имён — это одна стратегия (S2 из конфигураций и S2 из движка продвижения — один
    предмет); совпадение ИМЕНИ без общего идентификатора тождеством не является; при
    расхождении фактов двух источников победитель не выбирается — расхождение хранится
    рядом и остаётся видимым.
    """
    groups = {}
    for o in objects:
        groups.setdefault((o['id_namespace'], o['strategy_id']), []).append(o)
    merged, conflicts_total = [], 0
    for (namespace, sid), group in groups.items():
        base = dict(group[0])
        base['facts_by_source'] = {}
        for o in group:
            base['facts_by_source'][o['source']] = {
                'lifecycle_state': o['lifecycle_state'],
                'mode': o['mode'],
                'promotion_status': o['promotion_status'],
                'rnd_status': o['rnd_status'],
                'backtest_status': o['backtest_status'],
                'performance_metrics': o['performance_metrics'],
                'risk_limits': o['risk_limits'],
                'observed_at': o['observed_at'],
            }
        if len(group) > 1:
            base['sources'] = sorted({o['source'] for o in group})
            base['evidence'] = [e for o in group for e in o['evidence']]
            base['performance_metrics'] = [m for o in group
                                           for m in o['performance_metrics']]
            base['risk_limits'] = [x for o in group for x in o['risk_limits']]
            for field in ('lifecycle_state', 'mode', 'promotion_status'):
                values = {o[field] for o in group if o[field] is not None}
                if len(values) > 1:
                    conflicts_total += 1
                    base['conflicting_facts'].append({
                        'field': field, 'values': sorted(map(str, values)),
                        'by_source': {o['source']: o[field] for o in group},
                        'note': 'источники расходятся; правила, чей ответ сильнее, нет — '
                                'победитель НЕ выбирается'})
            base['lifecycle_state'] = ' | '.join(
                sorted({str(o['lifecycle_state']) for o in group}))
            promos = sorted({o['promotion_status'] for o in group
                             if o['promotion_status']})
            base['promotion_status'] = ' | '.join(promos) if promos else None
            modes = {o['mode'] for o in group}
            base['mode'] = modes.pop() if len(modes) == 1 else 'UNKNOWN'
            base['evidence'].append(_evidence(
                'cross_source_identity',
                f'один устойчивый идентификатор «{sid}» в пространстве {namespace} у '
                f"источников: {', '.join(base['sources'])}. Факты обоих сохранены, "
                'победитель не выбирается', 'investments'))
        merged.append(base)

    per_source = {}
    for o in objects:
        rec = per_source.setdefault(o['source'], {'records': 0, 'ids': set(),
                                                  'namespace': o['id_namespace']})
        rec['records'] += 1
        rec['ids'].add(o['strategy_id'])
    names = {}
    for o in objects:
        names.setdefault(o['strategy_name'].strip().lower(), set()).add(
            (o['id_namespace'], o['strategy_id']))
    name_only = sum(1 for keys in names.values() if len(keys) > 1)

    identity = {
        'per_source': {k: {'source_record_count': v['records'],
                           'stable_id_field': ('configs[].id'
                                               if k == 'strategy_configs.json' else
                                               'decisions[].strategy_id'
                                               if k == 'promotion_report.json' else
                                               'sleeves[].id'),
                           'id_namespace': v['namespace'],
                           'unique_ids': len(v['ids']),
                           'duplicate_ids': v['records'] - len(v['ids'])}
                       for k, v in sorted(per_source.items())},
        'strategy_source_records': len(objects),
        'proven_unique_strategy_ids': len(groups),
        'cross_source_exact_id_matches': sum(1 for g in groups.values() if len(g) > 1),
        'explicit_reference_matches': 0,
        'explicit_reference_basis': 'ни один инвестиционный источник не ссылается на '
                                    'идентификатор другого — измерено',
        'name_only_matches': name_only,
        'name_only_basis': 'совпадение имени без общего устойчивого идентификатора '
                           'тождеством НЕ является и объединением не становится',
        'no_proven_relation': sum(1 for g in groups.values() if len(g) == 1),
        'unresolved_strategy_identity_records': 0,
        'namespaces': sorted({o['id_namespace'] for o in objects}),
        'namespace_note': 'S-идентификаторы конфигураций и идентификаторы рукавов '
                          'лаборатории живут в РАЗНЫХ пространствах; совпадение между '
                          'ними тождеством не считалось бы',
        'conflicting_fact_count': conflicts_total,
        'authority_between_sources': 'AUTHORITY_UNDEFINED',
        'authority_note': 'правила, чей ответ сильнее при расхождении инвестиционных '
                          'источников, в репозитории нет — победителя не выбираем',
    }
    merged.sort(key=lambda o: (o['id_namespace'], o['strategy_id']))
    return merged, identity


LIMITS = (
    'Director OS не является инвестиционным движком: стратегии, доходность, риск и '
    'распределение капитала остаются за существующими источниками SPA.',
    'Режимы REAL, PAPER, SHADOW, FORECAST и R&D НИКОГДА не складываются в одно число. '
    'Бумажный капитал — не реальный, прогнозная доходность — не заработанная.',
    'Режим берётся только из объявления источника. Из имени файла режим не выводится, и '
    'is_demo=false режимом не является.',
    'Ничего не вычисляется: недостающие APY, PnL, риск и капитал остаются пустыми.',
    'Конвейер R&D взят у самого источника (strategy_lab_promotion.json). Своих стадий '
    'этот слой не придумывает.',
    'Запись движка продвижения — ПРЕДЛОЖЕНИЕ ИСТОЧНИКА, а не совет Director OS и не '
    'решение владельца.',
    'Одобрение владельца ставится только по улике; «готовность» гейтов одобрением не '
    'является.',
)


def _finish(production, now, sources, objects, capital, capital_evidence, real_proven,
            docs, by_name, pipeline, stage_counts, declared_capital_mode, identity,
            metrics):
    golive = docs.get('golive_status.json')
    kill = docs.get('kill_switch_status.json')
    risk = {}
    cfg = docs.get('capital_config.json')
    if isinstance(cfg, dict):
        risk['allocation_limits'] = cfg.get('allocation_limits')
        risk['risk_parameters'] = cfg.get('risk_parameters')
        risk['source'] = 'capital_config.json'
    kill_state = {
        'source': 'kill_switch_status.json',
        'status': by_name['kill_switch_status.json']['status'],
        'triggered': kill.get('triggered') if isinstance(kill, dict) else None,
        'reason': kill.get('reason') if isinstance(kill, dict) else None,
        'observed_at': by_name['kill_switch_status.json']['observed_at'],
        'note': 'только чтение: стоп-кран этим слоем не трогается ни при каких условиях',
    }
    golive_state = {
        'source': 'golive_status.json',
        'ready': golive.get('ready') if isinstance(golive, dict) else None,
        'passed': golive.get('passed') if isinstance(golive, dict) else None,
        'total': golive.get('total') if isinstance(golive, dict) else None,
        'blockers': (golive.get('blockers') or []) if isinstance(golive, dict) else [],
        'observed_at': by_name['golive_status.json']['observed_at'],
        'note': 'готовность гейтов — НЕ разрешение: решение о живых деньгах за владельцем '
                '(предмет №1 границы ADR-285)',
    }

    by = lambda key: {k: sum(1 for o in objects if o[key] == k)  # noqa: E731
                      for k in sorted({str(o[key]) for o in objects})}
    counts = {
        'objects': len(objects),
        'strategy_source_records': identity['strategy_source_records'],
        'proven_unique_strategy_ids': identity['proven_unique_strategy_ids'],
        'unresolved_strategy_identity_records':
            identity['unresolved_strategy_identity_records'],
        'cross_source_merges': identity['cross_source_exact_id_matches'],
        'conflicting_facts': identity['conflicting_fact_count'],
        'by_mode': by('mode'),
        'by_lifecycle_state': by('lifecycle_state'),
        'by_promotion_status': by('promotion_status'),
        'by_owner_approval': by('owner_approval_status'),
        'rnd_objects': sum(1 for o in objects if o['mode'] == 'RND'),
        'mode_unknown': sum(1 for o in objects if o['mode'] == 'UNKNOWN'),
        'with_capital': sum(1 for o in objects if o['capital_value'] is not None),
        'sources_read': sum(1 for s in sources if s['status'] == 'READ'),
        'sources_unavailable': sum(1 for s in sources if s['status'] != 'READ'),
        'sources_mode_declared': sum(1 for s in sources if s['mode'] != 'UNKNOWN'),
    }

    snapshot = {
        'schema_version': SCHEMA,
        'generated_at': now.isoformat(),
        'derived_state': True,
        'is_not_a_source_of_truth':
            'производный снимок инвестиций: пересобирается из существующих источников SPA '
            'и не является ни реестром стратегий, ни состоянием капитала',
        'is_not_an_investment_engine': True,
        'creates_strategies': False,
        'calculates_recommendations': False,
        'writes_capital': False,
        'production': str(production),
        'mode_definitions': dict(MODE_DEFINITIONS),
        'mode_vocabulary': list(MODES),
        'lifecycle_source': LIFECYCLE_SOURCE,
        'rnd_pipeline': pipeline,
        'rnd_stage_counts': stage_counts,
        'capital_by_mode': capital,
        'capital_metrics': metrics,
        'metric_definitions': dict(METRIC_DEFINITIONS),
        'metric_vocabulary': list(METRIC_TYPES),
        'capital_evidence': capital_evidence,
        'strategy_identity': identity,
        'real_capital_proven': real_proven,
        'real_capital_note':
            'РЕАЛЬНЫЙ капитал НЕ ИЗМЕРЕН и НЕ ДОКАЗАН: ни один источник не объявил режим '
            'REAL. Объявленный режим капитала — '
            f'{declared_capital_mode}' if not real_proven else
            'источник объявил режим REAL',
        'risk_limits': risk,
        'kill_switch': kill_state,
        'golive': golive_state,
        'sources': sources,
        'counts': counts,
        'objects': objects,
        'limits': list(LIMITS),
    }
    snapshot['semantic_digest'] = semantic_digest(snapshot)
    return snapshot


def semantic_view(snapshot):
    view = {k: v for k, v in snapshot.items()
            if k not in ('generated_at', 'semantic_digest', 'sources')}
    view['sources'] = [{k: v for k, v in s.items() if k != 'age_hours'}
                       for s in snapshot.get('sources', [])]
    return view


def semantic_digest(snapshot):
    payload = json.dumps(semantic_view(snapshot), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]


def validate_investment_snapshot(snapshot, where):
    def need(cond, message):
        if not cond:
            raise InvestmentInputError(f'{where}: {message}')

    need(isinstance(snapshot, dict), 'снимок не является объектом')
    need(snapshot.get('schema_version') == SCHEMA,
         f"схема {snapshot.get('schema_version')!r}, ожидалась {SCHEMA!r}")
    for key in ('generated_at', 'sources', 'counts', 'objects', 'limits',
                'mode_definitions', 'capital_by_mode', 'capital_evidence',
                'real_capital_proven', 'kill_switch', 'golive', 'lifecycle_source',
                'capital_metrics', 'metric_definitions', 'strategy_identity'):
        need(key in snapshot, f'поле {key} отсутствует')
    ident = snapshot['strategy_identity']
    need(ident['strategy_source_records'] >= ident['proven_unique_strategy_ids'],
         'уникальных идентификаторов больше, чем записей источников')
    need('тождеством НЕ является' in ident['name_only_basis'],
         'совпадение имени подано как тождество')
    need(ident['authority_between_sources'] == 'AUTHORITY_UNDEFINED'
         or 'победител' in ident['authority_note'],
         'между источниками выбран молчаливый победитель')
    for m in snapshot['capital_metrics']:
        need(m['metric_type'] in METRIC_TYPES,
             f"величина {m['metric_type']!r} вне словаря")
        need(m['mode'] in MODES, f"величина {m['metric_type']} с режимом вне словаря")
        need(bool(m.get('source')) and bool(m.get('source_field')),
             f"величина {m['metric_type']} без названного поля источника")
        need(not (m['currency'] is None and 'НЕ измерена' not in m['currency_basis']),
             f"величина {m['metric_type']}: валюта пуста без объяснения")
        need(not (m['mode'] == 'REAL' and not snapshot['real_capital_proven']),
             f"величина {m['metric_type']} объявлена REAL без доказанного режима")
    for flag in ('creates_strategies', 'calculates_recommendations', 'writes_capital'):
        need(snapshot.get(flag) is False, f'{flag} обязан быть False')
    need(snapshot.get('is_not_an_investment_engine') is True,
         'снимок обязан объявлять, что не является инвестиционным движком')
    cap = snapshot['capital_by_mode']
    need(set(cap) == set(MODES), 'капитал обязан быть разложен по ВСЕМ режимам')
    need(not (cap.get('REAL') is not None and not snapshot['real_capital_proven']),
         'реальный капитал назван числом, хотя режим REAL не доказан ни одним источником')
    seen = set()
    for i, o in enumerate(snapshot['objects']):
        for key in ('strategy_id', 'strategy_name', 'mode', 'lifecycle_state',
                    'capital_value', 'capital_currency', 'performance_metrics',
                    'yield_metrics', 'risk_classification', 'risk_limits', 'evidence',
                    'source', 'source_authority', 'observed_at', 'freshness',
                    'rnd_status', 'backtest_status', 'canary_status', 'promotion_status',
                    'owner_approval_status', 'related_decisions', 'related_work',
                    'related_findings'):
            need(key in o, f'objects[{i}] без поля {key}')
        need(o['strategy_id'] not in seen, f"дубль strategy_id {o['strategy_id']!r}")
        seen.add(o['strategy_id'])
        need(o['mode'] in MODES, f"objects[{i}] режим {o['mode']!r} вне словаря")
        need(o['owner_approval_status'] in APPROVAL_STATES,
             f"objects[{i}] одобрение {o['owner_approval_status']!r} вне словаря")
        need(bool(o['evidence']), f'objects[{i}] без улики')
        need('id_namespace' in o and 'facts_by_source' in o
             and 'conflicting_facts' in o,
             f'objects[{i}] без пространства имён или фактов по источникам')
        need(not (len(o['sources']) > 1 and not o['facts_by_source']),
             f'objects[{i}] объединён, но факты источников потеряны')
        need(not (o['mode'] == 'REAL' and not snapshot['real_capital_proven']),
             f'objects[{i}] объявлен REAL, хотя ни один источник режима REAL не объявлял')
        need(not (o['capital_value'] is not None and o['mode'] == 'UNKNOWN'),
             f'objects[{i}] несёт капитал при неизмеренном режиме — это и есть смешение')
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--production', type=Path, default=Path.home() / 'Documents/SPA_Claude')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)

    final = Path(args.output)
    if final.exists():
        raise SystemExit(f'{final} уже существует; каждый прогон пишет новый каталог')
    try:
        snapshot = build_investment_snapshot(args.production)
        validate_investment_snapshot(snapshot, 'freshly built')
    except InvestmentInputError as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\nСнимок не построен. Это НЕ '
                         '«инвестиций нет».')

    diff_mod.validate_output(final, [Path(args.production)])
    staging = final.with_name(final.name + '.incomplete')
    if staging.exists():
        raise SystemExit(f'{staging} остался от прерванного прогона; отодвиньте его')
    staging.mkdir(parents=True, mode=0o700)
    p = staging / 'investment_snapshot.json'
    with p.open('x', encoding='utf-8') as handle:
        # allow_nan=False: снимок обязан быть ВАЛИДНЫМ JSON, иначе страница молча
        # остаётся без раздела, а файл — нечитаемым для всех, кроме Python
        handle.write(json.dumps(snapshot, indent=2, ensure_ascii=False,
                                allow_nan=False) + '\n')
    p.chmod(0o600)
    os.rename(staging, final)

    c = snapshot['counts']
    print(f"Источников прочитано: {c['sources_read']} · недоступно: "
          f"{c['sources_unavailable']} · режим объявлен у {c['sources_mode_declared']}")
    print(f"Капитал по режимам (сводка): "
          f"{ {k: v for k, v in snapshot['capital_by_mode'].items() if v is not None} }")
    print(f"РЕАЛЬНЫЙ капитал доказан: {snapshot['real_capital_proven']} — "
          f"{snapshot['real_capital_note']}")
    idn = snapshot['strategy_identity']
    print(f"Записей о стратегиях: {idn['strategy_source_records']} · доказанных "
          f"уникальных идентификаторов: {idn['proven_unique_strategy_ids']} "
          f"(объединено по общему id: {idn['cross_source_exact_id_matches']}, "
          f"расхождений фактов: {idn['conflicting_fact_count']})")
    print(f"Объектов в снимке: {c['objects']} · по режиму: {c['by_mode']}")
    print('Величины по типам:')
    for m in snapshot['capital_metrics']:
        print(f"  {m['mode']}_{m['metric_type']:<20} {m['value']} "
              f"{m['currency'] or '(валюта НЕ измерена)'} ← {m['source']}."
              f"{m['source_field']}")
    print(f"R&D конвейер источника: {snapshot['rnd_pipeline']} · стадии: "
          f"{snapshot['rnd_stage_counts']}")
    k, g = snapshot['kill_switch'], snapshot['golive']
    print(f"Стоп-кран: triggered={k['triggered']} ({k['reason']}) · go-live гейты: "
          f"{g['passed']}/{g['total']}, ready={g['ready']}")
    print(f"Снимок → {final / 'investment_snapshot.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
