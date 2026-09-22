#!/usr/bin/env python3
"""Director OS v1.3 · CAPITAL, собранный по контракту правды.

Что здесь исправлено против v1.2 (каждая строка — найденный дефект)
===================================================================
1. **Окна доходности.** Было ``cum[-1] − cum[-1-n]`` — разность накопленных
   доходностей. Стало ``close[t] / close[t−N] − 1``. На нынешних сотых процента
   расхождение в четвёртом знаке, но метод неверен по роду, а не по точности.
2. **«Просадка» означала две величины.** Карточка брала ``summary.max_drawdown_pct``
   (−0.2047), график — построчное ``drawdown_pct`` (мин −0.0393). Теперь это две
   РАЗНЫЕ подписанные величины: МАКСИМАЛЬНАЯ и ТЕКУЩАЯ.
3. **−0.2047 % вообще не просадка.** Она целиком есть ступень между разогревочной и
   восстановленной сериями 10.06, и источник сам пишет об этом в ``note`` той строки:
   «SERIES BOUNDARY, not a real daily loss». v1.2 показывала её владельцу, а красная
   команда «подтвердила» её собственным пересчётом — пересчёт повторил арифметику
   источника и вместе с ней повторил её предмет. Честная максимальная просадка по
   подтверждённой серии — **−0.0393 %**, и она сходится с ``real_max_drawdown_pct``.
4. **Валюта.** v1.2 печатала «USDC» рядом с эквити, а ряд эквити валюту не объявляет.
   Но объявление ЕСТЬ — в ``capital_config.json`` полем ``capital.currency``. Поэтому
   валюта не выдумана и не убрана: она названа вместе с местом объявления.
5. **``deployed_usd`` и ``cash_usd`` выводились суммированием**, хотя источник объявляет
   оба поля сам. Теперь берутся объявленные, а сумма позиций служит ПЕРЕПРОВЕРКОЙ.
6. **``policy_compliant: false`` не был показан.** Показывается. Причину источник не
   объявляет, поэтому причина не придумывается: рядом идёт отдельно помеченная СВЕРКА
   слоя с объявленными порогами.
7. **Красные флаги подавались как «требует внимания по портфелю».** Ни один из них не
   про удерживаемый протокол. Теперь каждый флаг привязывается к портфелю уликой
   (держим / заблокирован / недавно вышли / связи нет) и попадает в своё место.
8. **Возраст данных скрывался.** У каждого факта есть ``observed_at`` и возраст.
9. **``real_*`` в источнике НЕ значит «реальные деньги».** ``real_days == evidenced_days``:
   это подтверждённая часть трека. Поля с этим префиксом переименованы на выходе, чтобы
   рядом с «REAL CAPITAL: NOT PROVEN» не стояло «real_total_return».

LLM запрещён. Только stdlib.
"""
from __future__ import annotations

from datetime import datetime, timezone

try:
    from . import owner_facts as F
except ImportError:                                   # запуск по пути, как это делает launchd
    import owner_facts as F

DOMAIN = 'CAPITAL'

#: Сроки годности объявлены ЗДЕСЬ и названы вслух: свежесть без объявленного срока —
#: это мнение, а не измерение. Цикл ходит раз в сутки, поэтому суточный ряд «свеж» до 30 ч.
SLO_HOURS = {
    'equity_series': 30.0,
    'positions': 30.0,
    'allocation': 30.0,
    'red_flags': 6.0,
    'golive': 30.0,
    'promotion': 30.0,
}

#: Где объявлена валюта. Ровно один адрес; если он исчезнет — валюты не будет.
CURRENCY_DECL = ('data/capital_config.json', 'capital.currency')

#: Вид APY. Смешивать их запрещено: «настроенный» и «ожидаемый» — не «текущий».
APY_KINDS = ('CURRENT_OBSERVED', 'HISTORICAL', 'CONFIGURED', 'EXPECTED', 'TARGET', 'UNKNOWN')

#: Классы привязки тревоги к портфелю. Это УЛИКА, а не оценка важности.
PORTFOLIO_LINKS = ('HELD', 'IN_TARGET', 'RECENTLY_EXITED', 'BLOCKED_CANDIDATE',
                   'NO_LINK_FOUND')


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _declared_currency(risk_config):
    """Валюта — только если её объявил источник. Иначе её нет, и точка."""
    cap = (risk_config or {}).get('capital') or {}
    cur = cap.get('currency')
    if not cur:
        return None, None
    return str(cur), f'{CURRENCY_DECL[0]}:{CURRENCY_DECL[1]}'


def _mode_of(doc):
    """Режим — из объявления источника. ``is_demo: false`` режимом REAL не читается."""
    raw = str((doc or {}).get('execution_mode') or '').lower()
    if 'simulation' in raw or raw in ('paper', 'read_only_simulation'):
        return 'PAPER'
    if raw in ('real', 'live'):
        return 'REAL'
    return 'UNKNOWN'


# ──────────────────────────────────────────────────────────────────────────────
#  Позиции, итоги и перепроверка
# ──────────────────────────────────────────────────────────────────────────────

def capital_totals(positions, *, currency, currency_basis, now):
    """Итоги капитала. ОБЪЯВЛЕННОЕ поле предпочитается выводу; вывод — перепроверка."""
    if not positions:
        return [F.not_measured(domain=DOMAIN, metric='equity_now',
                               source='data/current_positions.json',
                               reason='снимок позиций не прочитан — это НЕ значит, что капитала нет',
                               web_visibility='SAFE_FOR_PRIVATE_WEB')]
    src, field_of = 'data/current_positions.json', lambda k: k
    at = positions.get('generated_at')
    mode = _mode_of(positions)
    detail = positions.get('positions_detail') or {}
    independent_sum = None
    missing_leg = False
    if isinstance(detail, dict) and detail:
        parts = []
        for rec in detail.values():
            v = _f((rec or {}).get('usd'))
            if v is None:
                missing_leg = True      # НЕ ноль: потерянная нога подделала бы сумму
            else:
                parts.append(v)
        independent_sum = round(sum(parts), 2) if parts and not missing_leg else None

    def money(metric, key, *, relevance='INFORMATION_ONLY'):
        val = _f(positions.get(key))
        if val is None:
            return F.not_measured(domain=DOMAIN, metric=metric, source=src,
                                  reason=f'источник не объявил {key}', observed_at=at,
                                  mode=mode, web_visibility='SAFE_FOR_PRIVATE_WEB')
        return F.fact(domain=DOMAIN, metric=metric, value=val, unit='USD',
                      currency=currency, currency_basis=currency_basis,
                      source=src, source_field=field_of(key), authority='cycle_runner',
                      mode=mode, observed_at=at, slo_hours=SLO_HOURS['positions'], now=now,
                      owner_relevance=relevance, web_visibility='SAFE_FOR_PRIVATE_WEB')

    facts = [
        money('equity_now', 'current_equity_usd'),
        money('capital_base', 'capital_usd'),
        money('deployed_usd', 'deployed_usd'),
        money('cash_usd', 'cash_usd'),
        money('net_pnl_usd', 'net_pnl_usd'),
        money('accrued_yield_usd', 'accrued_yield_usd'),
        money('costs_paid_usd', 'costs_paid_usd'),
    ]
    by = {f['metric']: f for f in facts}

    # Перепроверка объявленного итога независимой суммой ног. Расхождение показывается.
    if independent_sum is not None and by['deployed_usd'].get('value') is not None:
        by['deployed_usd'] = F.with_conflict(
            by['deployed_usd'], other_value=independent_sum,
            other_source='независимая сумма positions_detail[].usd', tolerance=0.01)
    elif missing_leg:
        by['deployed_usd'] = dict(by['deployed_usd'],
                                  verification_state='UNVERIFIED',
                                  note='перепроверка невозможна: у позиции отсутствует usd, '
                                       'а подставлять ноль запрещено')
    cash_check = None
    if by['capital_base'].get('value') is not None and by['deployed_usd'].get('value') is not None:
        cash_check = round(by['capital_base']['value'] - by['deployed_usd']['value'], 2)
    if cash_check is not None and by['cash_usd'].get('value') is not None:
        by['cash_usd'] = F.with_conflict(by['cash_usd'], other_value=cash_check,
                                         other_source='capital_usd − deployed_usd',
                                         tolerance=0.01)
    return [by[f['metric']] for f in facts]


def position_rows(positions, *, currency, currency_basis, now):
    """Строки позиций. APY здесь — ТЕКУЩИЙ НАБЛЮДЁННЫЙ, и у него своя отметка времени."""
    detail = (positions or {}).get('positions_detail') or {}
    rows = []
    for name, rec in (detail.items() if isinstance(detail, dict) else ()):
        rec = rec or {}
        usd, apy = _f(rec.get('usd')), _f(rec.get('apy_pct'))
        src_kind = str(rec.get('apy_source') or '').lower()
        kind = 'CURRENT_OBSERVED' if src_kind == 'live' else (
            'CONFIGURED' if src_kind in ('static', 'config') else 'UNKNOWN')
        rows.append({
            'protocol': str(name),
            'usd': usd,
            'usd_absent_reason': None if usd is not None else 'источник не объявил usd',
            'apy_pct': apy,
            'apy_kind': kind,
            'apy_source_declared': rec.get('apy_source'),
            'apy_observed_at': rec.get('as_of'),
            'apy_age_hours': F.age_hours(rec.get('as_of'), now=now),
            'share_pct': None,
        })
    total = sum(r['usd'] for r in rows if r['usd'] is not None)
    for r in rows:
        if r['usd'] is not None and total:
            r['share_pct'] = round(r['usd'] / total * 100.0, 4)
    rows.sort(key=lambda r: (r['usd'] is None, -(r['usd'] or 0)))
    return rows


def target_allocation(alloc, *, now):
    """ЦЕЛЬ/ТЕНЬ — отдельная сущность, и ни одна её доля не рисуется как текущая."""
    if not alloc:
        return {'state': 'NOT_MEASURED',
                'reason': 'источник целевой аллокации не прочитан'}
    shadow = alloc.get('decision_shadow') or {}
    mode = str(alloc.get('mode') or 'UNKNOWN').upper()
    legs = []
    for leg in shadow.get('legs') or ():
        if not isinstance(leg, dict):
            continue
        legs.append({'protocol': leg.get('protocol'),
                     'delta_usd': _f(leg.get('delta_usd')),
                     'direction': leg.get('direction')})
    gates = shadow.get('gates') or {}
    blocking = sorted(k for k, v in gates.items() if v is False)
    return {
        'state': 'READ',
        # Нераспознанный режим — UNKNOWN, а не SHADOW: назвать чужой режим теневым
        # значит утверждать про него то, чего источник не говорил.
        'mode': mode if mode in F.MODES else 'UNKNOWN',
        'mode_declared': alloc.get('mode'),
        'observation_kind': 'SHADOW_PROPOSED',
        'decision': shadow.get('decision'),
        'reasons': list(shadow.get('reasons') or ()),
        'legs': legs,
        'leg_count': len(legs),
        'apy_now_pp': _f(shadow.get('apy_now_pp')),
        'apy_opt_pp': _f(shadow.get('apy_opt_pp')),
        'gain_pp': _f(shadow.get('gain_pp')),
        'required_gain_pp': _f(shadow.get('required_gain_pp')),
        'cost_usd': _f(shadow.get('cost_usd')),
        'payback_days': _f(shadow.get('payback_days')),
        'gates_total': len(gates),
        'gates_blocking': blocking,
        'observed_at': alloc.get('generated_at'),
        'age_hours': F.age_hours(alloc.get('generated_at'), now=now),
        'advisory_note': ((alloc.get('advisor_notes') or {}).get('note')
                          or alloc.get('note')),
        'is_advisory': True,
        'advisory_basis': 'источник сам объявляет режим SHADOW и пишет, что вердикт '
                          'ADVISORY и ни одной позиции не двигал',
    }


# ──────────────────────────────────────────────────────────────────────────────
#  Соответствие политике — показать, но не выдумать причину
# ──────────────────────────────────────────────────────────────────────────────

def policy_compliance(positions, risk_config, *, now):
    """``policy_compliant`` источника + ОТДЕЛЬНО помеченная сверка слоя с порогами.

    Источник объявляет вердикт и не объявляет причины. Причина не придумывается:
    сверка ниже — наблюдение слоя над объявленными порогами, и она так и подписана.
    Совпадение сверки с вердиктом не доказывает, что причина именно та.
    """
    if not positions or 'policy_compliant' not in positions:
        return {'state': 'NOT_MEASURED',
                'reason': 'источник не объявляет policy_compliant'}
    declared = positions.get('policy_compliant')
    limits = ((risk_config or {}).get('allocation_limits') or {})
    cap = _f(positions.get('capital_usd'))
    checks = []
    if cap:
        for name, usd in (positions.get('positions') or {}).items():
            v = _f(usd)
            if v is None:
                checks.append({'check': f'доля {name}', 'state': 'NOT_MEASURED',
                               'reason': 'сумма позиции не объявлена'})
                continue
            share = round(v / cap * 100.0, 4)
            ceiling = _f(limits.get('max_per_protocol_t1_pct'))
            checks.append({'check': f'доля {name}', 'value_pct': share,
                           'ceiling_pct': ceiling,
                           'state': 'AT_OR_OVER' if (ceiling is not None and share >= ceiling)
                                    else ('OK' if ceiling is not None else 'NO_CEILING_DECLARED')})
    vs = positions.get('validation_summary') or {}
    for key, lim_key, direction in (('cash_pct', 'min_cash_buffer_pct', 'min'),
                                    ('t2_pct', 'max_t2_total_pct', 'max')):
        val, lim = _f(vs.get(key)), _f(limits.get(lim_key))
        if val is None or lim is None:
            checks.append({'check': key, 'state': 'NOT_MEASURED',
                           'reason': 'значение или порог не объявлены'})
            continue
        at = (val <= lim) if direction == 'min' else (val >= lim)
        checks.append({'check': key, 'value_pct': val, 'ceiling_pct': lim,
                       'direction': direction,
                       'state': 'AT_OR_OVER' if at else 'OK'})
    return {
        'state': 'READ',
        # `policy_compliant: null` — это «не измерено», а не «не соответствует».
        # Через bool() неизмеренное подняло бы тревогу DECISION_REQUIRED на пустом месте.
        'declared_compliant': (None if declared is None else bool(declared)),
        'declared_field': 'data/current_positions.json:policy_compliant',
        'policy_version': positions.get('policy_version'),
        'reason_declared_by_source': None,
        'reason_note': 'источник объявляет вердикт и НЕ объявляет причину; причина не '
                       'выводится — сверка ниже принадлежит кокпиту, а не источнику',
        'layer_checks': checks,
        'layer_checks_at_or_over': [c['check'] for c in checks
                                    if c.get('state') == 'AT_OR_OVER'],
        'observed_at': positions.get('generated_at'),
        'age_hours': F.age_hours(positions.get('generated_at'), now=now),
    }


# ──────────────────────────────────────────────────────────────────────────────
#  Внимание владельца — только с уликой относимости
# ──────────────────────────────────────────────────────────────────────────────

def _normalise(name):
    return str(name or '').lower().replace('-', '_').replace(' ', '_')


#: Минимальная длина имени, при которой совпадение по вхождению ещё что-то значит.
#: Короткие обрывки совпадают со всем подряд, и мост превратился бы в решето.
_MIN_TOKEN = 4


def _link_of(protocol, *, held, in_target, exited, blocked):
    """Привязка тревоги к портфелю по УЛИКЕ, с НАЗВАННЫМ правилом сопоставления.

    Мост нужен потому, что источники зовут один протокол по-разному: монитор пишет
    ``ethena-susde`` и ``pendle-pt``, книга позиций — ``susde`` и ``pendle``. Правило
    сопоставления названо вслух и возвращается вместе с ответом, чтобы его можно было
    оспорить, а не обнаружить. Точное совпадение сильнее вхождения, поэтому порядок
    проверок именно такой.
    """
    n = _normalise(protocol)
    for label, population in (('HELD', held), ('IN_TARGET', in_target),
                              ('RECENTLY_EXITED', exited), ('BLOCKED_CANDIDATE', blocked)):
        for item in population:
            m = _normalise(item)
            if not m:
                continue
            if n == m:
                return label, item, 'EXACT'
            if len(m) >= _MIN_TOKEN and m in n:
                return label, item, 'SOURCE_NAME_CONTAINS_PORTFOLIO_NAME'
            if len(n) >= _MIN_TOKEN and n in m:
                return label, item, 'PORTFOLIO_NAME_CONTAINS_SOURCE_NAME'
    return 'NO_LINK_FOUND', None, 'NO_RULE_MATCHED'


def attention_items(*, red_flags, positions, alloc, policy, now):
    """Производная проекция внимания.

    Попасть сюда можно, только выполнив ЧЕТЫРЕ условия: относимость доказана уликой,
    наблюдение свежо по объявленному сроку, у важности есть источник, и сказано, чего
    ждут от владельца. Тревога о протоколе, которого нет ни в портфеле, ни в цели, ни в
    недавних выходах, ни в кандидатах, во «внимание по портфелю» не попадает никогда.
    """
    held = list((positions or {}).get('positions_detail') or {})
    in_target = [l.get('protocol') for l in ((alloc or {}).get('decision_shadow') or {}).get('legs') or ()
                 if isinstance(l, dict)]
    hist = ((alloc or {}).get('history') or {}).get('last_move_legs') or {}
    exited = [k for k, v in hist.items() if (_f(v) or 0) < 0]
    blocked = list((((positions or {}).get('feed_coverage') or {}).get('blocked')) or {})

    items, deferred = [], []
    rf = red_flags or {}
    fallback = bool(rf.get('fallback_used'))
    observed = rf.get('generated_at')
    age = F.age_hours(observed, now=now)
    fresh = F.freshness_of(age, slo_hours=SLO_HOURS['red_flags'])
    for flag in rf.get('red_flags') or ():
        if not isinstance(flag, dict):
            continue
        proto = flag.get('protocol')
        link, matched, match_rule = _link_of(proto, held=held, in_target=in_target,
                                             exited=exited, blocked=blocked)
        ev = flag.get('evidence') or {}
        grade = ev.get('grade')
        item = {
            'kind': 'RISK_FLAG',
            'subject': proto,
            'category': flag.get('category'),
            'severity': flag.get('severity'),
            'severity_source': f"{flag.get('source')} (monitor v{rf.get('monitor_version')})",
            'message': flag.get('message'),
            'portfolio_link': link,
            'portfolio_link_matched': matched,
            'portfolio_link_rule': match_rule,
            'observed_at': observed,
            'age_hours': age,
            'freshness_state': fresh,
            'evidence_grade': grade if grade not in (None, '', '?') else None,
            'evidence_grade_absent': grade in (None, '', '?'),
            'monitor_fallback_used': fallback,
            'owner_relevance': 'INFORMATION_ONLY',
            'placement': None,
        }
        if link in ('HELD', 'IN_TARGET'):
            item['placement'] = 'PORTFOLIO_ATTENTION'
            item['owner_relevance'] = 'INFORMATION_ONLY'
            items.append(item)
        elif link in ('RECENTLY_EXITED', 'BLOCKED_CANDIDATE'):
            item['placement'] = 'WATCHLIST_RND'
            item['placement_basis'] = (
                'протокол не удерживается: он либо недавно закрыт, либо стоит в списке '
                'заблокированных кандидатов источника — это наблюдение за кандидатом, '
                'а не тревога по портфелю')
            deferred.append(item)
        else:
            item['placement'] = 'NOT_RELEVANT_TO_PORTFOLIO'
            item['placement_basis'] = ('связь с портфелем не доказана ни одной уликой; '
                                       'показывать это как «требует внимания» было бы '
                                       'тревогой не о том')
            deferred.append(item)

    # Несоответствие политике — предмет решения, и у него есть объявленный источник.
    if policy and policy.get('state') == 'READ' and policy.get('declared_compliant') is False:
        items.append({
            'kind': 'POLICY',
            'subject': 'портфель',
            'severity': 'DECLARED_NON_COMPLIANT',
            'severity_source': policy['declared_field'],
            'message': 'источник объявляет портфель НЕ соответствующим политике',
            'reason_declared': None,
            'reason_note': policy['reason_note'],
            'layer_checks_at_or_over': policy.get('layer_checks_at_or_over') or [],
            'portfolio_link': 'HELD',
            'observed_at': policy.get('observed_at'),
            'age_hours': policy.get('age_hours'),
            'owner_relevance': 'DECISION_REQUIRED',
            'placement': 'PORTFOLIO_ATTENTION',
        })
    order = {'DECISION_REQUIRED': 0, 'ACTION_REQUIRED': 1, 'INFORMATION_ONLY': 2, 'UNKNOWN': 3}
    items.sort(key=lambda i: (order.get(i.get('owner_relevance'), 9),
                              0 if i.get('severity') == 'CRITICAL' else 1))
    return {'portfolio_attention': items,
            'portfolio_attention_count': len(items),
            'watchlist_rnd': [d for d in deferred if d['placement'] == 'WATCHLIST_RND'],
            'not_relevant': [d for d in deferred if d['placement'] == 'NOT_RELEVANT_TO_PORTFOLIO'],
            'admission_rule': ('во внимание по портфелю попадает только то, у чего '
                               'относимость доказана уликой, наблюдение свежо по '
                               'объявленному сроку, важность имеет источник и названо, '
                               'чего ждут от владельца')}
