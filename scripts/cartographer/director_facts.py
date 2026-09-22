#!/usr/bin/env python3
"""Director OS v1.3 · Сборка набора фактов владельца.

Один набор фактов на весь кокпит
================================
Каждое число, которое владелец может увидеть, рождается здесь и обязано пройти
``owner_facts.fact()``. Отрисовка не считает НИЧЕГО: она получает готовые факты с
паспортом и раскладывает их по экрану. Поэтому «откуда это число» перестаёт быть
вопросом к автору страницы и становится полем.

Дайджест смысла берётся с набора фактов, а не с дерева проекции: в него входят только
поля из объявленного списка смысловых. Отметка наблюдения смысла не меняет — и теперь
это свойство по построению, а не по полноте списка исключений.

Только stdlib. LLM запрещён.
"""
from __future__ import annotations

from datetime import datetime, timezone

try:
    from . import owner_facts as F
    from . import capital_truth as CT
except ImportError:
    import owner_facts as F
    import capital_truth as CT

SCHEMA = 'director_facts/1'


def _now():
    return datetime.now(timezone.utc)


def _series_facts(history, *, currency, currency_basis, mode, now):
    """Факты, выведенные из ряда эквити. Каждый — с формулой и с оговорками ряда."""
    src = 'data/equity_curve_daily.json'
    if not history:
        return [], {'state': 'NOT_MEASURED', 'reason': 'ряд эквити не подан'}
    daily = history.get('daily') or []
    summary = history.get('summary') or {}
    points, dropped = F.parse_series(daily)
    integrity = F.calendar_integrity(points)
    boundaries = F.series_boundaries(points)
    anchor_index = next((i for i, (_d, _e, row) in enumerate(points)
                         if row.get('evidenced')), None)

    segments = {}
    for _d, _e, row in points:
        key = str(row.get('source') or 'UNKNOWN')
        segments[key] = segments.get(key, 0) + 1

    quality = {
        'state': 'MEASURED',
        'points': len(points),
        'dropped_rows': dropped,
        'first_date': integrity.get('first_date'),
        'last_date': integrity.get('last_date'),
        'calendar_days_span': integrity.get('calendar_days_span'),
        'missing_dates': integrity.get('missing_dates'),
        'missing_count': integrity.get('missing_count'),
        'duplicate_dates': integrity.get('duplicate_dates'),
        'duplicate_count': integrity.get('duplicate_count'),
        'series_boundaries': [d.isoformat() for d in boundaries],
        'segments_by_source': segments,
        'anchor_index': anchor_index,
        'anchor_date': (points[anchor_index][0].isoformat()
                        if anchor_index is not None else None),
        'evidenced_points': sum(1 for _d, _e, r in points if r.get('evidenced')),
        'unverified_points': sum(1 for _d, _e, r in points if not r.get('evidenced')),
        'boundary_note':
            'источник сам объявляет разрыв ряда полем series_reset и пишет в примечании, '
            'что ступень эквити на этой дате — ГРАНИЦА СЕРИЙ, а не дневной убыток. '
            'Метрика, посчитанная сквозь границу, измеряет склейку, а не капитал',
        'gap_note':
            'пропущенные календарные даты НЕ рисуются как соседние точки: расстояние '
            'на оси времени соответствует календарю',
    }

    facts = []

    def series_fact(metric, result, *, relevance='INFORMATION_ONLY', unit='%',
                    kind='DERIVED', extra=None):
        if result.get('state') != 'MEASURED':
            return F.not_measured(domain=CT.DOMAIN, metric=metric, source=src,
                                  reason=result.get('reason') or 'не измерено',
                                  mode=mode, observed_at=history.get('observed_at'),
                                  web_visibility='SAFE_FOR_PRIVATE_WEB')
        f = F.fact(domain=CT.DOMAIN, metric=metric, value=result['value'], unit=unit,
                   currency=currency if unit == 'USD' else None,
                   currency_basis=currency_basis if unit == 'USD' else None,
                   source=src, source_field='daily[].close_equity',
                   authority='cycle_runner', mode=mode, fact_kind=kind,
                   derivation=result.get('derivation'),
                   observed_at=history.get('observed_at'),
                   slo_hours=CT.SLO_HOURS['equity_series'], now=now,
                   owner_relevance=relevance, web_visibility='SAFE_FOR_PRIVATE_WEB')
        f['window'] = {k: result.get(k) for k in
                       ('window_requested_days', 'window_actual_days', 'precision',
                        'start_date', 'end_date', 'peak_date', 'trough_date',
                        'base_field', 'segments', 'as_of_date')
                       if result.get(k) is not None}
        if extra:
            f.update(extra)
        return f

    for days, metric in ((1, 'return_1d'), (7, 'return_7d'), (30, 'return_30d')):
        facts.append(series_fact(metric, F.window_return(points, days,
                                                         boundaries=boundaries)))

    # ── «За всё время» считается от ОБЪЯВЛЕННОГО источником основания.
    declared_start = summary.get('start_equity')
    total = F.total_return(points, declared_base=declared_start,
                           declared_base_field='summary.start_equity',
                           boundaries=boundaries)
    total_fact = series_fact('return_since_available_start', total)
    if total.get('crosses_series_boundary'):
        total_fact['caveat'] = {
            'kind': 'CROSSES_SERIES_BOUNDARY',
            'boundaries': total['crosses_series_boundary'],
            'note': 'окно включает объявленный разрыв ряда: часть «дохода» есть склейка '
                    'двух серий, а не движение капитала'}
    facts.append(total_fact)

    if anchor_index is not None:
        anchor_base = summary.get('real_start_equity')
        anchor = F.total_return(points, since_index=anchor_index,
                                declared_base=anchor_base,
                                declared_base_field='summary.real_start_equity',
                                boundaries=boundaries)
        anchor_fact = series_fact('return_since_evidenced_start', anchor,
                                  relevance='INFORMATION_ONLY')
        # Перепроверка объявленного основания: оно обязано совпасть с открытием якорной
        # строки. Если нет — расхождение показывается, а не сглаживается.
        anchor_row = points[anchor_index][2]
        declared_open = anchor_row.get('open_equity')
        if anchor_base is not None and declared_open is not None:
            anchor_fact = F.with_conflict(
                anchor_fact,
                other_value=round((points[-1][1] / declared_open - 1) * 100.0, 6)
                if declared_open else None,
                other_source='пересчёт от open_equity якорной строки', tolerance=0.001)
        facts.append(anchor_fact)

    md = F.max_drawdown(points, boundaries=boundaries)
    md_fact = series_fact('max_drawdown_evidenced', md)
    naive = F.max_drawdown(points)
    if (md.get('state') == 'MEASURED' and naive.get('state') == 'MEASURED'
            and abs(md['value'] - naive['value']) > 1e-6):
        md_fact['caveat'] = {
            'kind': 'BOUNDARY_AWARE',
            'naive_value': naive['value'],
            'note': 'без учёта объявленного разрыва ряда та же формула даёт '
                    f'{naive["value"]} % — это ступень между сериями, а не просадка. '
                    'Именно её показывал предыдущий выпуск'}
    declared_md = summary.get('real_max_drawdown_pct')
    if declared_md is not None and md.get('state') == 'MEASURED':
        md_fact = F.with_conflict(md_fact, other_value=declared_md,
                                  other_source='summary.real_max_drawdown_pct',
                                  tolerance=0.001)
        md_fact.setdefault('caveat', None)
    facts.append(md_fact)

    facts.append(series_fact('current_drawdown', F.current_drawdown(points)))

    for metric, key, unit in (('evidenced_days', 'evidenced_days', 'дней'),
                              ('series_points', 'num_days', 'точек')):
        val = summary.get(key)
        facts.append(F.fact(domain=CT.DOMAIN, metric=metric, value=val, unit=unit,
                            source=src, source_field=f'summary.{key}',
                            authority='cycle_runner', mode=mode,
                            observed_at=history.get('observed_at'),
                            slo_hours=CT.SLO_HOURS['equity_series'], now=now,
                            web_visibility='SAFE_FOR_PRIVATE_WEB')
                     if val is not None else
                     F.not_measured(domain=CT.DOMAIN, metric=metric, source=src,
                                    reason=f'источник не объявил summary.{key}',
                                    web_visibility='SAFE_FOR_PRIVATE_WEB'))
    return facts, quality


def build_capital_facts(*, history=None, positions=None, risk_config=None,
                        red_flags=None, allocation=None, now=None):
    """Полный набор фактов слоя CAPITAL плюс сопутствующие разборы."""
    now = now or _now()
    currency, currency_basis = CT._declared_currency(risk_config)
    mode = CT._mode_of(positions) if positions else CT._mode_of(history or {})
    if history is not None:
        history = dict(history)
        history.setdefault('observed_at', (positions or {}).get('generated_at'))

    facts = list(CT.capital_totals(positions, currency=currency,
                                   currency_basis=currency_basis, now=now))
    series, quality = _series_facts(history, currency=currency,
                                    currency_basis=currency_basis, mode=mode, now=now)
    facts.extend(series)

    policy = CT.policy_compliance(positions, risk_config, now=now)
    if policy.get('state') == 'READ':
        facts.append(F.fact(
            domain=CT.DOMAIN, metric='policy_compliant',
            value=policy['declared_compliant'], unit=None,
            source='data/current_positions.json', source_field='policy_compliant',
            authority='cycle_runner', mode=mode,
            observed_at=policy.get('observed_at'),
            slo_hours=CT.SLO_HOURS['positions'], now=now,
            owner_relevance=('DECISION_REQUIRED' if policy['declared_compliant'] is False
                             else 'INFORMATION_ONLY'),
            web_visibility='SAFE_FOR_PRIVATE_WEB',
            note=policy['reason_note']))

    apy = _apy_facts(positions=positions, risk_config=risk_config,
                     allocation=allocation, mode=mode, now=now)
    facts.extend(apy)

    attention = CT.attention_items(red_flags=red_flags, positions=positions,
                                   alloc=allocation, policy=policy, now=now)
    return {
        'schema': SCHEMA,
        'facts': facts,
        'fact_count': len(facts),
        'history_quality': quality,
        'positions': CT.position_rows(positions, currency=currency,
                                      currency_basis=currency_basis, now=now),
        'target': CT.target_allocation(allocation, now=now),
        'policy': policy,
        'attention': attention,
        'currency': currency,
        'currency_basis': currency_basis,
        'currency_note': ('валюта объявлена отдельным источником; ряд эквити её не '
                          'объявляет, и приписывать её экраном запрещено'),
        'mode': mode,
    }


def _apy_facts(*, positions, risk_config, allocation, mode, now):
    """Виды APY. «Настроенный» и «ожидаемый» никогда не подаются как «текущий»."""
    out = []
    shadow = (allocation or {}).get('decision_shadow') or {}
    now_pp = shadow.get('apy_now_pp')
    if now_pp is not None:
        out.append(F.fact(domain=CT.DOMAIN, metric='apy_portfolio_current', value=now_pp,
                          unit='% годовых', source='data/allocation_rationale.json',
                          source_field='decision_shadow.apy_now_pp',
                          authority='allocator', mode=mode,
                          observation_kind='CURRENT_OBSERVED',
                          observed_at=(allocation or {}).get('generated_at'),
                          slo_hours=CT.SLO_HOURS['allocation'], now=now,
                          web_visibility='SAFE_FOR_PRIVATE_WEB'))
    opt = shadow.get('apy_opt_pp')
    if opt is not None:
        out.append(F.fact(domain=CT.DOMAIN, metric='apy_portfolio_optimum', value=opt,
                          unit='% годовых', source='data/allocation_rationale.json',
                          source_field='decision_shadow.apy_opt_pp',
                          authority='allocator', mode='SHADOW',
                          observation_kind='SHADOW_PROPOSED',
                          observed_at=(allocation or {}).get('generated_at'),
                          slo_hours=CT.SLO_HOURS['allocation'], now=now,
                          web_visibility='SAFE_FOR_PRIVATE_WEB'))
    tuner = (positions or {}).get('tuner_expected_apy')
    if tuner is not None:
        out.append(F.fact(domain=CT.DOMAIN, metric='apy_expected', value=tuner,
                          unit='% годовых', source='data/current_positions.json',
                          source_field='tuner_expected_apy', authority='tuner',
                          mode=mode, observation_kind='EXPECTED',
                          observed_at=(positions or {}).get('generated_at'),
                          slo_hours=CT.SLO_HOURS['positions'], now=now,
                          web_visibility='SAFE_FOR_PRIVATE_WEB',
                          note='это ОЖИДАНИЕ тюнера, а не наблюдённая доходность'))
    target = ((risk_config or {}).get('performance_targets') or {}).get('target_apy_pct')
    if target is not None:
        out.append(F.fact(domain=CT.DOMAIN, metric='apy_target', value=target,
                          unit='% годовых', source='data/capital_config.json',
                          source_field='performance_targets.target_apy_pct',
                          authority='ADR', mode=mode, observation_kind='TARGET_POLICY',
                          freshness_state='TIMELESS', now=now,
                          web_visibility='SAFE_FOR_PRIVATE_WEB',
                          note='это ЦЕЛЬ, поставленная решением, а не замер'))
    return out


def digest(facts):
    """Отпечаток смысла набора фактов."""
    return F.semantic_digest(facts)
