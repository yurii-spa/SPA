#!/usr/bin/env python3
"""Director Shell (v1.1 Epic 1) — закрытая оболочка владельца из web-safe проекции.

Три слоя, и смешивать их нельзя
===============================
``CAPITAL`` — что происходит с моими деньгами.
``STUDIO``  — как работает моя автономная система.
``BUILD``   — что я хочу изменить или построить.

Это границы навигации, объявленные владельцем, а не удобная группировка. Четвёртого слоя
контракт не пропустит.

Чего эта оболочка НЕ делает
===========================
Ни одной кнопки действия. ``+ Создать`` нарисован намеренно — владелец должен видеть, куда
идёт продукт, — но он помечен ``ПОКА НЕ ВКЛЮЧЕНО`` и не является элементом ``<button>``:
нечего нажать, значит нечего и исполнить. Ни одного сетевого вызова: страница читает только
то, что в неё вложено при сборке.

Мобильное — не «уменьшенный десктоп»
====================================
На телефоне навигация — нижние вкладки под большой палец. На широком экране те же три слоя
переезжают наверх. Сведения одни и те же: скрывать от телефона нечего.

PWA без офлайн-кеша данных
==========================
Манифест и иконки есть — ярлык на домашнем экране ставится. Service worker НЕ добавляется
намеренно: безопасная офлайн-модель для приватных данных ещё не объявлена, а кеш, который
переживёт выход из системы, — это утечка с отсрочкой. Пустой кеш честнее быстрого.

LLM здесь запрещён. Ничего не исполняется.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.cartographer import diff as diff_mod  # noqa: E402

LAYERS = (
    ('capital', 'CAPITAL', '💰', 'Что происходит с моими деньгами'),
    ('studio', 'STUDIO', '🏭', 'Как работает моя автономная система'),
    ('build', 'BUILD', '🧭', 'Что я хочу изменить или построить'),
)

SHELL_FILE = 'index.html'
MANIFEST_FILE = 'manifest.webmanifest'
ICON_FILE = 'icon.svg'

#: Бюджет строк на блок. Тот же, что у центра директора v1: экран владельца — не выгрузка.
TOP_N = 5

#: Имена блоков на языке владельца. Слаг вроде `acceptance_not_measured` — язык разработчика;
#: «owner-first» и developer dashboard отличаются ровно здесь. Неизвестный слаг остаётся
#: как есть: выдумывать ему название значило бы переводить то, чего не понял.
BLOCK_LABELS = {
    'owner_decisions': 'Нужно моё решение',
    'attention_now': 'Требует внимания сейчас',
    'current_work': 'Сейчас строится',
    'blocked': 'Заблокировано',
    'acceptance_attention': 'Приёмка требует внимания',
    'acceptance_not_measured': 'Приёмка не измерена',
    'system_drift': 'Системные расхождения',
    'unverified_state': 'Состояние не подтверждено',
}

#: Классы данных РЕАЛЬНОГО режима на языке владельца.
REAL_CLASS_LABELS = {
    'REAL_CAPITAL_SUMMARY': 'Сводная сумма реальных денег',
    'REAL_POSITION_DETAIL': 'Разбивка по позициям и протоколам',
    'WALLET_ACCOUNT_IDENTIFIER': 'Адреса кошельков и номера счетов',
    'RAW_INVESTMENT_EVIDENCE': 'Сырые улики: выписки, ответы узлов, хеши сделок',
}


def e(value):
    return html.escape('' if value is None else str(value), quote=True)


def _num(value):
    """Число для человека. ``None`` остаётся «не измерено» — не нулём (инв. #17)."""
    if value is None:
        return 'не измерено'
    if isinstance(value, bool):
        return 'да' if value else 'нет'
    if isinstance(value, float):
        return f'{value:,.2f}'.replace(',', ' ')
    if isinstance(value, int):
        return f'{value:,}'.replace(',', ' ')
    return str(value)


def _kv(pairs):
    rows = ''.join(f'<div class="kv"><span class="k">{e(k)}</span>'
                   f'<span class="v">{e(_num(v))}</span></div>' for k, v in pairs)
    return f'<div class="kvs">{rows}</div>'


def _counter_row(mapping, limit=8):
    if not mapping:
        return '<p class="muted">не измерено</p>'
    items = sorted(mapping.items(), key=lambda kv: (-(kv[1] or 0), kv[0]))[:limit]
    chips = ''.join(f'<span class="chip"><b>{e(_num(v))}</b> {e(k)}</span>' for k, v in items)
    return f'<div class="chips">{chips}</div>'


def _card(title, body, note=None, tone=''):
    note_html = f'<p class="note">{e(note)}</p>' if note else ''
    return (f'<section class="card {tone}"><h2>{e(title)}</h2>{note_html}{body}</section>')



# ── Графики: только инлайн-SVG и только там, где ряд ДЕЙСТВИТЕЛЬНО ряд ────────
#
# Внешних библиотек нет по построению: страница обязана работать без сети. Одна точка
# графиком не становится — из снимка «историю» не делают, и это проверяется числом.

CHART_MIN_POINTS = 2


def _sparkline(values, *, width=320, height=64, zero_line=False, label=''):
    """Линия по ряду чисел. Меньше двух точек — честный отказ, а не пустая рамка."""
    pts = [v for v in values if isinstance(v, (int, float))]
    if len(pts) < CHART_MIN_POINTS:
        return (f'<p class="muted">график не строится: точек {len(pts)}, нужно от '
                f'{CHART_MIN_POINTS}. Один снимок историей не является</p>')
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    step = width / (len(pts) - 1)
    coords = ' '.join(
        f'{i * step:.1f},{height - (v - lo) / span * (height - 6) - 3:.1f}'
        for i, v in enumerate(pts))
    base = ''
    if zero_line and lo <= 0 <= hi:
        y = height - (0 - lo) / span * (height - 6) - 3
        base = f'<line x1="0" y1="{y:.1f}" x2="{width}" y2="{y:.1f}" class="zero"/>'
    area = f'0,{height} {coords} {width},{height}'
    return (f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{e(label)}" preserveAspectRatio="none">'
            f'<polygon class="fill" points="{area}"/>{base}'
            f'<polyline class="line" points="{coords}"/></svg>')


def _bars(mapping, *, limit=8, label=''):
    """Столбики по словарю-счётчику. Ноль и «не измерено» — разные вещи."""
    items = [(k, v) for k, v in (mapping or {}).items() if isinstance(v, (int, float))]
    if not items:
        return '<p class="muted">не измерено</p>'
    items.sort(key=lambda kv: -kv[1])
    items = items[:limit]
    top = max(v for _k, v in items) or 1
    rows = ''.join(
        f'<div class="bar"><span class="barname">{e(k)}</span>'
        f'<span class="bartrack"><span class="barfill" style="width:{v / top * 100:.1f}%">'
        f'</span></span><span class="barval">{e(_num(v))}</span></div>'
        for k, v in items)
    return f'<div class="bars" role="img" aria-label="{e(label)}">{rows}</div>'


def _stat(value, caption, *, tone=''):
    return (f'<div class="stat {tone}"><span class="statv">{e(_num(value))}</span>'
            f'<span class="statc">{e(caption)}</span></div>')


def _stats(items):
    return '<div class="stats">' + ''.join(_stat(v, c, tone=t) for v, c, t in items) + '</div>'


def _details(summary, body, *, note=None):
    """Подробности прячутся по умолчанию: экран владельца — не выгрузка."""
    note_html = f'<p class="note">{e(note)}</p>' if note else ''
    return (f'<details class="drill"><summary>{e(summary)}</summary>'
            f'{note_html}{body}</details>')


def _pct(value, digits=2):
    if value is None:
        return 'не измерено'
    try:
        return f'{float(value):+.{digits}f} %'
    except (TypeError, ValueError):
        return str(value)


def _money(value, currency=None):
    if value is None:
        return 'не измерено'
    try:
        body = f'{float(value):,.2f}'.replace(',', ' ')
    except (TypeError, ValueError):
        return str(value)
    return f'{body} {currency}' if currency else body


# ── CAPITAL ───────────────────────────────────────────────────────────────────
def render_capital(layer):
    if layer.get('state') == 'NOT_READ':
        return _card('Капитал', f'<p class="muted">{e(layer.get("note"))}</p>', tone='unknown')

    out = []
    hist = layer.get('history') or {}
    summary = hist.get('summary') or {}
    pos = layer.get('positions') or {}

    # ── 1. ОБЗОР: первые секунды владельца ────────────────────────────────────
    mode = hist.get('mode') or (pos.get('mode'))
    out.append(_card(
        'Сейчас',
        _stats([
            (summary.get('end_equity'), 'эквити, USDC', ''),
            (pos.get('deployed_usd'), 'вложено', ''),
            (pos.get('cash_usd'), 'в кэше', ''),
            (summary.get('total_return_pct'), 'доход за всё, %',
             'ok' if (summary.get('total_return_pct') or 0) > 0 else ''),
            (summary.get('max_drawdown_pct'), 'макс. просадка, %', 'warn'),
            (summary.get('evidenced_days'), 'дней подтверждено', ''),
        ]),
        note=(f'режим объявлен источником: {mode}. ' + (hist.get('mode_basis') or ''))
             if mode else 'режим капитала не объявлен источником',
        tone='ok'))

    if not layer.get('real_capital_proven'):
        out.append(_card(
            'REAL CAPITAL: NOT PROVEN',
            f'<p>{e(layer.get("real_capital_note"))}</p>',
            note='это замер, а не оценка: ни один источник не объявил режим REAL поимённо',
            tone='warn'))

    by_mode = layer.get('capital_by_mode') or {}
    rows = ''.join(
        f'<div class="mode {"nil" if by_mode.get(m) is None else ""}">'
        f'<span class="k">{e(m)}</span>'
        f'<span class="v">{e(_money(by_mode.get(m)))}</span></div>'
        for m in ('REAL', 'PAPER', 'SHADOW', 'FORECAST', 'RND', 'UNKNOWN')
        if m in by_mode)
    out.append(_card('Капитал по режимам', f'<div class="modes">{rows}</div>',
                     note='режимы НИКОГДА не складываются в одно число'))

    # ── 2. ДОХОДНОСТЬ: графики только по настоящему ряду ──────────────────────
    daily = hist.get('daily') or []
    if hist.get('is_a_series'):
        eq = [r.get('equity') or r.get('close_equity') for r in daily]
        dd = [r.get('drawdown_pct') for r in daily]
        windows = _return_windows(daily)
        out.append(_card(
            'Доходность',
            _stats([(windows['d1'], 'за день, %', ''),
                    (windows['d7'], 'за 7 дней, %', ''),
                    (windows['d30'], 'за 30 дней, %', ''),
                    (summary.get('total_return_pct'), 'с начала, %', '')])
            + '<h3>Эквити</h3>' + _sparkline(eq, label='кривая эквити')
            + f'<p class="note">{e(len(daily))} дневных точек · '
              f'{e(summary.get("num_days"))} дней, из них подтверждено '
              f'{e(summary.get("evidenced_days"))}</p>'
            + '<h3>Просадка</h3>' + _sparkline(dd, zero_line=True, label='просадка')
            + _details('Лучший и худший день', _kv([
                ('лучший день', (summary.get('best_day') or {}).get('date')),
                ('его доходность, %', (summary.get('best_day') or {}).get('daily_return_pct')),
                ('худший день', (summary.get('worst_day') or {}).get('date')),
                ('его доходность, %', (summary.get('worst_day') or {}).get('daily_return_pct')),
                ('начальное эквити', summary.get('start_equity')),
                ('текущее эквити', summary.get('end_equity')),
            ])),
            note='окна считаются по накопленной доходности ряда; дни без подтверждения '
                 'в ряду остаются и помечены источником'))
    else:
        out.append(_card('Доходность',
                         '<p class="muted">ряда нет: ' + e(hist.get('state', 'NOT_MEASURED'))
                         + '</p>',
                         note=e(hist.get('series_rule') or hist.get('note') or ''),
                         tone='unknown'))

    # ── 3. ПОЗИЦИИ И АЛЛОКАЦИЯ ────────────────────────────────────────────────
    if pos.get('state') == 'READ' and pos.get('positions'):
        rows = ''.join(
            f'<tr><td>{e(r.get("protocol"))}</td>'
            f'<td class="num">{e(_money(r.get("usd")))}</td>'
            f'<td class="num">{e(_pct(r.get("apy_pct")))}</td>'
            f'<td>{e(r.get("apy_source") or "не объявлен")}</td></tr>'
            for r in pos['positions'])
        alloc = {r.get('protocol'): r.get('usd') for r in pos['positions']}
        out.append(_card(
            'Куда вложено',
            _bars(alloc, label='аллокация по протоколам')
            + '<table><thead><tr><th>протокол</th><th class="num">сумма</th>'
              '<th class="num">APY</th><th>источник APY</th></tr></thead>'
              f'<tbody>{rows}</tbody></table>',
            note='адресов кошельков и номеров счетов здесь нет ни одного — их не '
                 'содержит и сам источник'))
    else:
        out.append(_card('Куда вложено', '<p class="muted">не измерено</p>', tone='unknown'))

    # ── 4. СТРАТЕГИИ: группировкой, а не выгрузкой ───────────────────────────
    counts = layer.get('counts') or {}
    strategies = layer.get('strategies') or []
    out.append(_card(
        'Стратегии',
        _bars(counts.get('by_lifecycle_state') or {}, label='по жизненному циклу')
        + _kv([('объектов всего', counts.get('objects')),
               ('доказанно уникальных id', counts.get('proven_unique_strategy_ids')),
               ('с капиталом', counts.get('with_capital')),
               ('противоречивых фактов', counts.get('conflicting_facts')),
               ('режим не определён', counts.get('mode_unknown'))])
        + _details(f'Разбор по режимам и продвижению',
                   _bars(counts.get('by_mode') or {}, label='по режимам')
                   + _bars(counts.get('by_promotion_status') or {}, label='по продвижению')
                   + _bars(counts.get('by_owner_approval') or {}, label='по одобрению'),
                   note=f'записей в снимке {len(strategies)}; полный список намеренно '
                        'не разворачивается — это выгрузка, а не экран'),
        note='Director OS НЕ Investment Engine: стратегии здесь только читаются'))

    # ── 5. РИСК ───────────────────────────────────────────────────────────────
    ks = layer.get('kill_switch') or {}
    gl = layer.get('golive') or {}
    risk = layer.get('risk_config') or {}
    limits = risk.get('allocation_limits') or {}
    params = risk.get('risk_parameters') or {}
    flags = layer.get('red_flags') or {}
    risk_body = _kv([
        ('стоп-кран сработал', ks.get('triggered')),
        ('основание', ks.get('reason')),
        ('гейты go-live', f"{_num(gl.get('passed'))} из {_num(gl.get('total'))}"),
        ('готовность объявлена', gl.get('ready')),
        ('дней реального трека', gl.get('real_track_days')),
    ])
    if limits or params:
        risk_body += _details('Пороги, объявленные решением', _kv([
            ('мин. буфер кэша, %', limits.get('min_cash_buffer_pct')),
            ('потолок на протокол T1, %', limits.get('max_per_protocol_t1_pct')),
            ('потолок на протокол T2, %', limits.get('max_per_protocol_t2_pct')),
            ('потолок T2 всего, %', limits.get('max_t2_total_pct')),
            ('floor TVL, USD', limits.get('tvl_floor_usd')),
            ('стоп по просадке, %', params.get('max_drawdown_kill_pct')),
            ('границы APY, %', f"{_num(params.get('apy_floor_pct'))} … "
                               f"{_num(params.get('apy_ceiling_pct'))}"),
            ('мин. дней на бумаге до живых', params.get('min_paper_days_before_live')),
        ]), note='пороги меняются решением, а не наблюдением: это не замер, а правило')
    out.append(_card('Риск и стоп-кран', risk_body,
                     note='только чтение: ни стоп-кран, ни лимиты этой оболочкой '
                          'не трогаются'))

    if flags.get('state') == 'READ' and flags.get('flags'):
        rows = ''.join(
            f'<tr class="sev-{e(str(f.get("severity")).lower())}">'
            f'<td>{e(f.get("severity"))}</td><td>{e(f.get("protocol"))}</td>'
            f'<td>{e(f.get("category"))}</td><td>{e(f.get("message"))}</td></tr>'
            for f in flags['flags'])
        out.append(_card(
            f'Красные флаги протоколов: {flags.get("count")}',
            '<table><thead><tr><th>важность</th><th>протокол</th><th>вид</th>'
            f'<th>что измерено</th></tr></thead><tbody>{rows}</tbody></table>',
            note='это наблюдения монитора, а не решения: капитал ими не двигается',
            tone='warn'))

    # ── 6. R&D И ПРОДВИЖЕНИЕ ─────────────────────────────────────────────────
    rnd = layer.get('rnd_stage_counts') or {}
    promo = layer.get('promotion') or {}
    rnd_body = _bars(rnd, label='стадии R&D')
    if promo.get('state') == 'READ':
        rows = ''.join(
            f'<tr><td>{e(d.get("strategy_id"))}</td><td>{e(d.get("action"))}</td>'
            f'<td>{e(str(d.get("reason"))[:90])}</td></tr>'
            for d in (promo.get('decisions') or [])[:TOP_N])
        rnd_body += _bars(promo.get('by_action') or {}, label='решения о продвижении')
        rnd_body += _details(
            f'Решения о продвижении: {promo.get("count")}',
            '<table><thead><tr><th>стратегия</th><th>решение</th><th>основание</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>',
            note=e(promo.get('note') or ''))
    else:
        rnd_body += '<p class="muted">решения о продвижении не измерены</p>'
    out.append(_card('Инвестиционный R&D', rnd_body,
                     note='кокпит не даёт инвестиционных рекомендаций и не создаёт '
                          'стратегий'))

    # ── 7. ЧТО ТРЕБУЕТ ВНИМАНИЯ ──────────────────────────────────────────────
    attention = _capital_attention(layer)
    if attention:
        items = ''.join(f'<li>{e(x)}</li>' for x in attention)
        out.append(_card('Что требует моего внимания', f'<ul>{items}</ul>',
                         note='каждая строка — следствие ИЗМЕРЕННОГО факта; '
                              'важность не выдумывается',
                         tone='warn'))

    # ── Политика реальных денег и границы ────────────────────────────────────
    policy = layer.get('real_web_policy') or {}
    if policy:
        order = ('REAL_CAPITAL_SUMMARY', 'REAL_POSITION_DETAIL',
                 'WALLET_ACCOUNT_IDENTIFIER', 'RAW_INVESTMENT_EVIDENCE')
        rows = ''.join(
            f'<tr><td>{e(REAL_CLASS_LABELS.get(k, k))}</td>'
            f'<td class="{"never" if policy.get(k) == "NEVER" else "blocked"}">'
            f'{e(policy.get(k))}</td></tr>'
            for k in order if k in policy)
        out.append(_details('Реальные деньги: что будет показано, когда появятся',
                            '<table><thead><tr><th>класс данных</th>'
                            f'<th>в закрытом вебе</th></tr></thead><tbody>{rows}</tbody>'
                            '</table>',
                            note=layer.get('real_policy_note') or ''))

    limits_list = layer.get('limits') or []
    if limits_list:
        items = ''.join(f'<li>{e(x)}</li>' for x in limits_list[:TOP_N])
        more = (f'<p class="note">показано {min(len(limits_list), TOP_N)} из '
                f'{len(limits_list)}</p>' if len(limits_list) > TOP_N else '')
        out.append(_details('Границы этого слоя', f'<ul>{items}</ul>{more}'))
    return ''.join(out)


def _return_windows(daily):
    """Доходность за 1/7/30 дней ПО РЯДУ. Нет глубины — «не измерено», не ноль."""
    def at(n):
        if len(daily) <= n:
            return None
        a = daily[-1 - n].get('cumulative_return_pct')
        b = daily[-1].get('cumulative_return_pct')
        if a is None or b is None:
            return None
        return round(b - a, 4)
    return {'d1': at(1), 'd7': at(7), 'd30': at(30)}


def _capital_attention(layer):
    """Строки внимания — только из измеренного. Severity не изобретается."""
    out = []
    if not layer.get('real_capital_proven'):
        out.append('Режим REAL не доказан ни одним источником — живых денег кокпит '
                   'не видит')
    flags = (layer.get('red_flags') or {})
    crit = sum(1 for f in flags.get('flags') or []
               if str(f.get('severity')).upper() == 'CRITICAL')
    if crit:
        out.append(f'Красных флагов уровня CRITICAL: {crit} — наблюдение монитора '
                   'протоколов')
    gl = layer.get('golive') or {}
    if gl.get('blocker_count'):
        out.append(f'Блокеров go-live: {gl["blocker_count"]}')
    counts = layer.get('counts') or {}
    if counts.get('conflicting_facts'):
        out.append(f'Источники спорят о {counts["conflicting_facts"]} фактах стратегий — '
                   'победитель не выбирается')
    if counts.get('mode_unknown'):
        out.append(f'Стратегий без объявленного режима: {counts["mode_unknown"]}')
    if (layer.get('positions') or {}).get('state') != 'READ':
        out.append('Позиции не измерены')
    hist = layer.get('history') or {}
    if hist.get('state') == 'READ':
        s = hist.get('summary') or {}
        if s.get('num_days') and s.get('evidenced_days') is not None:
            gap = s['num_days'] - s['evidenced_days']
            if gap > 0:
                out.append(f'Дней в ряду без подтверждения: {gap} из {s["num_days"]}')
    return out


# ── STUDIO ────────────────────────────────────────────────────────────────────
def render_studio(layer, architect=None, cio=None, bridge=None):
    out = []
    rel = layer.get('reliability') or {}
    rc = rel.get('counts') or {}
    work = layer.get('work') or {}
    wc = work.get('counts') or {}
    gov = layer.get('governance') or {}
    gc = gov.get('counts') or {}
    svc = layer.get('services') or {}
    drift = layer.get('drift') or {}

    # ── 1. СВОДКА ВЛАДЕЛЬЦА ──────────────────────────────────────────────────
    state = layer.get('system_state')
    tone = {'НОРМАЛЬНО': 'ok', 'ТРЕБУЕТ ВНИМАНИЯ': 'warn'}.get(state, 'unknown')
    out.append(_card(
        f'Состояние системы: {state or "НЕ ИЗМЕРЕНО"}',
        _stats([
            (wc.get('waiting_owner'), 'ждёт меня', 'warn'),
            (wc.get('in_progress'), 'строится', ''),
            (wc.get('blocked'), 'заблокировано', 'warn'),
            (rc.get('active_confirmed'), 'подтв. проблем', 'warn'),
            (rc.get('critical_confirmed_now'), 'из них CRITICAL', 'warn'),
            ((drift.get('by_drift_status') or {}).get('AUTHORITY_UNDEFINED'),
             'без авторитета', ''),
        ])
        + f'<p>{e(layer.get("system_state_reason"))}</p>',
        note='общего балла здоровья нет намеренно: разные риски в один балл не сводятся',
        tone=tone))

    blocks = layer.get('blocks') or {}
    if blocks:
        rows = ''.join(
            f'<tr><td>{e(BLOCK_LABELS.get(name, name))}</td>'
            f'<td class="num">{e(_num(b.get("shown")))}</td>'
            f'<td class="num">{e(_num(b.get("count")))}</td></tr>'
            for name, b in sorted(blocks.items(), key=lambda kv: -(kv[1].get('count') or 0)))
        out.append(_card('Что требует внимания',
                         '<table><thead><tr><th>блок</th><th class="num">показано</th>'
                         f'<th class="num">всего</th></tr></thead><tbody>{rows}</tbody>'
                         '</table>',
                         note=f'на экране не больше {TOP_N} строк в блоке; полное число '
                              'в правой колонке'))

    # ── 2. СЛУЖБЫ ФЛОТА ──────────────────────────────────────────────────────
    if svc.get('state') == 'READ':
        by_status = svc.get('by_status') or {}
        body = (_stats([(svc.get('count'), 'служб всего', ''),
                        (by_status.get('LIVE'), 'LIVE', 'ok'),
                        (by_status.get('DEGRADED'), 'DEGRADED', 'warn'),
                        (by_status.get('STALE'), 'STALE', 'warn'),
                        (by_status.get('LEGACY'), 'LEGACY', ''),
                        (svc.get('health_not_measured'), 'здоровье НЕ измерено', 'unknown')])
                + '<h3>По роду</h3>' + _bars(svc.get('by_kind') or {}, label='род')
                + '<h3>По роли</h3>' + _bars(svc.get('by_role') or {}, limit=12,
                                             label='роль'))
        rows = ''.join(
            f'<tr><td>{e(s.get("name"))}</td><td>{e(s.get("status"))}</td>'
            f'<td>{e(s.get("kind"))}</td><td>{e(s.get("role"))}</td>'
            f'<td>{e(s.get("schedule"))}</td><td>{e(_stage_word(s.get("stages")))}</td></tr>'
            for s in sorted(svc.get('services') or [],
                            key=lambda x: (str(x.get('status')), str(x.get('name')))))
        body += _details(
            f'Все службы: {svc.get("count")}',
            '<table><thead><tr><th>имя</th><th>состояние</th><th>род</th><th>роль</th>'
            f'<th>расписание</th><th>стадия</th></tr></thead><tbody>{rows}</tbody></table>',
            note=svc.get('agent_note') or '')
        out.append(_card('Службы', body,
                         note='«здоровье не измерено» означает отсутствие семантической '
                              'пробы, а не плохое состояние'))
    else:
        out.append(_card('Службы', '<p class="muted">не измерено</p>', tone='unknown'))

    # ── 3. РАСХОЖДЕНИЕ ИСТОЧНИКА ПРАВДЫ ──────────────────────────────────────
    if drift.get('state') == 'READ':
        out.append(_card(
            'Источник правды и расхождения',
            _stats([(drift.get('entities'), 'сущностей', ''),
                    ((drift.get('by_drift_status') or {}).get('IN_SYNC'), 'в согласии', 'ok'),
                    ((drift.get('by_drift_status') or {}).get('AUTHORITY_UNDEFINED'),
                     'авторитет не объявлен', 'unknown')])
            + _bars(drift.get('by_drift_status') or {}, limit=10, label='расхождения'),
            note='«авторитет не объявлен» — это НЕ расхождение и НЕ ошибка: никто не '
                 'сказал, какая копия главная'))

    # ── 4. НАДЁЖНОСТЬ ────────────────────────────────────────────────────────
    top = rel.get('top_findings') or {}
    rel_body = (_bars(rc.get('by_classification') or {}, label='классификация')
                + _bars(rc.get('by_severity') or {}, label='важность')
                + _kv([('подтверждено сейчас', rc.get('active_confirmed')),
                       ('требует перепроверки', rc.get('active_unverified')),
                       ('CRITICAL подтверждённых', rc.get('critical_confirmed_now')),
                       ('подтверждено разными источниками', rc.get('corroborated'))]))
    if top.get('rows'):
        rows = ''.join(
            f'<tr class="sev-{e(str(f.get("severity")).lower())}">'
            f'<td>{e(f.get("severity"))}</td><td>{e(f.get("classification"))}</td>'
            f'<td>{e(str(f.get("finding_title"))[:110])}</td></tr>'
            for f in top['rows'])
        rel_body += _details(
            f'Подтверждённые сейчас: показано {top.get("shown")} из '
            f'{top.get("confirmed_total")}',
            '<table><thead><tr><th>важность</th><th>класс</th><th>что измерено</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>',
            note=top.get('note') or '')
    out.append(_card('Надёжность', rel_body,
                     note='«требует перепроверки» — это НЕ расхождение и не инцидент'))

    # ── 5. РАБОТА ────────────────────────────────────────────────────────────
    ident = work.get('identity') or {}
    out.append(_card(
        'Работа',
        _bars(wc.get('by_owner_view_state') or {}, limit=10, label='состояние работ')
        + _kv([('ждёт владельца', wc.get('waiting_owner')),
               ('заблокировано', wc.get('blocked')),
               ('в работе', wc.get('in_progress')),
               ('закрыто всего', wc.get('completed_total')),
               ('приёмка: расхождений', wc.get('acceptance_state_conflicts')),
               ('неразрешённых идентичностей', wc.get('unresolved_identity_records')),
               ('уникальных работ доказано', ident.get('proven_unique_work_count'))])
        + _details('Откуда берутся работы',
                   _bars(wc.get('by_source_state') or {}, label='по источнику')
                   + _bars(wc.get('by_work_type') or {}, label='по виду'),
                   note='трекер и KANBAN — РАЗНЫЕ реестры. Их числа не складываются: '
                        'одна работа может лежать в обоих, и это не доказано ни для '
                        'одной записи'),
        note='один заголовок в двух реестрах — НЕ доказательство, что работа одна'))

    # ── 6. АРХИТЕКТОР И CIO ──────────────────────────────────────────────────
    for title, rec, would in (
            ('Архитектор', architect,
             'работающий агент, который читает входящее и выдаёт разбор в канонической '
             'форме; сегодня найдены только документы'),
            ('CIO', cio,
             'работающий агент инвестиционного разбора с артефактом и расписанием; '
             'сегодня найден только документ на 16 аналитиков')):
        rec = rec or {'state': 'UNKNOWN', 'note': 'состояние не подавали'}
        st = rec.get('state', 'UNKNOWN')
        out.append(_card(f'{title}: {st}',
                         f'<p>{e(rec.get("note"))}</p>'
                         + _details('Что сделало бы его LIVE', f'<p>{e(would)}</p>'),
                         note='DOCUMENTED_ONLY означает: документ есть, работающей '
                              'реализации не найдено. Изображать её работающей нельзя',
                         tone='unknown' if st != 'LIVE' else 'ok'))

    # ── 7. ЁМКОСТЬ ───────────────────────────────────────────────────────────
    out.append(_card('Ёмкость Claude и вычислений: НЕ ИЗМЕРЕНО',
                     '<p class="muted">канонического источника ёмкости не найдено: ни '
                     'числа сессий, ни очереди, ни лимита. Показывать здесь что-либо '
                     'значило бы выдумать.</p>',
                     note='пробел записан в перечень недостающего',
                     tone='unknown'))

    # ── 8. УПРАВЛЕНИЕ, ВОССТАНОВЛЕНИЕ, БЕЗОПАСНОСТЬ ─────────────────────────
    out.append(_card(
        'Управление и восстановление',
        _bars(gc.get('by_recovery_status') or gc.get('by_recovery_state') or {},
              label='восстановление')
        + _kv([('гейтов владельца', gc.get('owner_gated')),
               ('автономных правил', gc.get('autonomous_rules')),
               ('аварийных правил', gc.get('emergency_rules')),
               ('коллизий номеров ADR', gc.get('adr_number_collisions')),
               ('резервов наблюдено', gc.get('backups_observed')),
               ('восстановление испытано', gc.get('recovery_tested')),
               ('зона требуется, но не объявлена', gc.get('zone_required_but_missing'))])
        + _details('Разрешения и зоны',
                   _bars(gc.get('by_permission_class') or {}, label='классы разрешений')
                   + _bars(gc.get('by_zone_scope') or {}, label='область зоны')),
        note='резерв наблюдён ≠ восстановление испытано; runbook описан ≠ испытан. '
             'Отсутствие записей о тревогах НЕ означает «безопасно»'))

    # ── 9. ПАМЯТЬ ────────────────────────────────────────────────────────────
    mem = layer.get('memory') or {}
    if mem.get('systems'):
        rows = ''.join(
            f'<tr><td>{e(m.get("name"))}</td><td>{e(m.get("state"))}</td>'
            f'<td>{e(m.get("note"))}</td></tr>' for m in mem['systems'])
        out.append(_card(
            f'Память: {mem.get("state")}',
            '<table><thead><tr><th>система</th><th>состояние</th><th>что это</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>',
            note=mem.get('note') or ''))
    else:
        out.append(_card('Память', '<p class="muted">не измерено</p>', tone='unknown'))

    # ── 10. РЕПОЗИТОРИИ И ВЫПУСКИ ────────────────────────────────────────────
    out.append(_card(
        'Выпуски: РЕЕСТРА НЕ СУЩЕСТВУЕТ',
        '<p class="muted">общего реестра выпусков в репозитории нет — замер 20.09. '
        'Есть одна узкая запись (пин проверяющего скрипта), журнал коммитов и файл '
        'готовности; ни один из них реестром выпусков не является.</p>',
        note='изобретать второй реестр во время выпуска запрещено',
        tone='unknown'))

    # ── 11. BRIDGE ───────────────────────────────────────────────────────────
    if bridge:
        d = bridge.get('daemons') or {}
        db = bridge.get('db') or {}
        code = bridge.get('code') or {}
        out.append(_card(
            f'Bridge: {bridge.get("state", "UNKNOWN")}',
            _stats([(db.get('tasks'), 'задач', ''), (db.get('runs'), 'прогонов', ''),
                    (db.get('turns'), 'ходов', ''), (db.get('gates'), 'гейтов', ''),
                    (db.get('artifacts'), 'улик исполнения', 'warn')])
            + _kv([('репозиторий', bridge.get('repo'))] + sorted(d.items())
                  + sorted(code.items())),
            note=bridge.get('note') or '',
            tone='ok' if bridge.get('state') == 'LIVE' else 'unknown'))
    return ''.join(out)


def _stage_word(stages):
    """Самая дальняя ДОСТИГНУТАЯ стадия. ``null`` — не измерено, не «нет»."""
    if not isinstance(stages, dict):
        return 'не измерено'
    order = ('DECLARED', 'REGISTERED', 'INSTALLED', 'LOADED', 'RUNNING',
             'PRODUCING_OUTPUT', 'HEALTHY')
    reached = [s for s in order if stages.get(s) is True]
    if not reached:
        return 'не измерено'
    nxt = next((s for s in order if stages.get(s) is None), None)
    return reached[-1] + (f' · далее не измерено' if nxt else '')


# ── BUILD ─────────────────────────────────────────────────────────────────────
def render_build(layer, *, work=None):
    out = []
    pipe = layer.get('pipeline') or {}

    # ── 1. ГДЕ ОСТАНАВЛИВАЕТСЯ АВТОНОМИЯ — первое, что должен увидеть владелец ─
    if pipe.get('state') == 'READ':
        by = pipe.get('by_state') or {}
        rows = ''.join(
            f'<div class="stage st-{e(str(s.get("state")).lower())}">'
            f'<span class="stname">{e(s.get("stage"))}</span>'
            f'<span class="stbadge">{e(s.get("state"))}</span>'
            f'<span class="stbasis">{e(s.get("basis"))}</span></div>'
            for s in pipe.get('stages') or [])
        stops = pipe.get('autonomy_stops_at')
        out.append(_card(
            'Путь от моей мысли до доставки',
            _stats([(by.get('LIVE'), 'работает', 'ok'),
                    (by.get('PARTIAL'), 'частично', 'warn'),
                    (by.get('DOCUMENTED_ONLY'), 'только на бумаге', 'unknown'),
                    (by.get('NOT_FOUND'), 'не найдено', 'unknown')])
            + (f'<p class="lead">Автономия останавливается на: <b>{e(stops)}</b></p>'
               if stops else '<p class="lead">Все стадии работают.</p>')
            + f'<div class="stages">{rows}</div>',
            note=pipe.get('note') or '',
            tone='warn' if stops else 'ok'))
    else:
        out.append(_card('Путь от моей мысли до доставки',
                         '<p class="muted">не измерено</p>',
                         note=pipe.get('note') or '', tone='unknown'))

    # ── 2. «+ Создать» — нарисован, но не элемент управления ────────────────
    out.append(
        '<section class="card disabled" aria-disabled="true">'
        '<div class="create"><span class="plus">+</span>'
        '<span class="createlabel">Создать</span>'
        '<span class="badge">ПОКА НЕ ВКЛЮЧЕНО</span></div>'
        '<p class="note">так это будет выглядеть. Сейчас действий нет ни одного: '
        'ни задачи, ни исполнения, ни одобрения отсюда не запускается.</p>'
        '</section>')

    # ── 3. ЧЕМ УЖЕ МОЖНО ПОДАТЬ ЗАДАЧУ ──────────────────────────────────────
    intake = layer.get('owner_intake') or []
    if intake:
        rows = ''.join(
            f'<tr class="{"yes" if i.get("available") else "no"}">'
            f'<td>{e(i.get("intake_kind"))}</td>'
            f'<td>{"есть" if i.get("available") else "НЕ НАЙДЕНО"}</td>'
            f'<td>{e(i.get("note"))}</td></tr>' for i in intake)
        out.append(_card('Чем я уже могу подать задачу',
                         '<table><thead><tr><th>вид</th><th>состояние</th>'
                         f'<th>как</th></tr></thead><tbody>{rows}</tbody></table>',
                         note='это замер существующих каналов, а не план'))

    # ── 4. ТЕКУЩАЯ РАБОТА ПО СТАДИЯМ ────────────────────────────────────────
    wc = ((work or {}).get('counts') or {})
    if wc:
        out.append(_card(
            'Что сейчас в работе',
            _stats([(wc.get('waiting_owner'), 'ждёт меня', 'warn'),
                    (wc.get('in_progress'), 'делается', ''),
                    (wc.get('blocked'), 'заблокировано', 'warn'),
                    (wc.get('completed_total'), 'закрыто', 'ok')])
            + _bars(wc.get('by_owner_view_state') or {}, limit=9,
                    label='состояние работ'),
            note='состояния берутся из карточек как есть; «закрыто» не означает '
                 '«принято» — приёмка считается отдельно'))

    # ── 5. BRIDGE КАК ОПОРА ─────────────────────────────────────────────────
    bridge = layer.get('bridge') or {}
    if bridge and bridge.get('state') != 'NOT_MEASURED':
        db = bridge.get('db') or {}
        code = bridge.get('code') or {}
        d = bridge.get('daemons') or {}
        out.append(_card(
            f'Bridge — опора конвейера: {bridge.get("state")}',
            _stats([(db.get('tasks'), 'задач', ''), (db.get('runs'), 'прогонов', ''),
                    (db.get('turns'), 'ходов', ''),
                    (db.get('artifacts'), 'улик исполнения', 'warn')])
            + _kv(sorted(d.items()) + sorted(code.items())),
            note=bridge.get('note') or '',
            tone='ok' if bridge.get('state') == 'LIVE' else 'unknown'))

    # ── 6. ПОЧЕМУ КНОПОК НЕТ ────────────────────────────────────────────────
    audit = layer.get('action_audit') or {}
    ac = audit.get('counts') or {}
    body = _stats([(ac.get('candidates'), 'кандидатов', ''),
                   (ac.get('ready_for_ui'), 'готовы для UI', 'warn'),
                   (ac.get('not_ready'), 'не готовы', ''),
                   (ac.get('red_zone'), 'запрещено навсегда', 'warn')])
    actions = audit.get('actions') or []
    if actions:
        rows = ''.join(
            f'<tr><td>{e(a.get("action"))}</td><td>{e(a.get("verdict"))}</td>'
            f'<td>{e(", ".join(a.get("missing_properties") or []) or "—")}</td></tr>'
            for a in actions[:TOP_N])
        body += _details(f'Разобранные действия: {len(actions)}',
                         '<table><thead><tr><th>действие</th><th>вердикт</th>'
                         f'<th>чего не хватает</th></tr></thead><tbody>{rows}</tbody>'
                         '</table>')
    red = audit.get('red_zone') or []
    if red:
        chips = ''.join(f'<span class="chip red">{e(x)}</span>' for x in red)
        body += _details('Красная зона — не обсуждается',
                         f'<div class="chips">{chips}</div>',
                         note='эти глаголы не попадают в UI ни при каких свойствах')
    out.append(_card('Почему кнопок нет', body,
                     note='ноль готовых действий — это ИЗМЕРЕНО, а не решено',
                     tone='warn'))
    return ''.join(out)


CSS = """
:root{--bg:#0f1115;--card:#171a21;--line:#252a34;--fg:#e8eaf0;--mut:#9aa3b2;
--ok:#3fb950;--warn:#d29922;--unk:#6e7681;--red:#f85149;--acc:#58a6ff;--tab:64px}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
-webkit-text-size-adjust:100%}
body{padding:0 0 calc(var(--tab) + env(safe-area-inset-bottom,0px))}
header{position:sticky;top:0;z-index:5;background:rgba(15,17,21,.94);
backdrop-filter:blur(8px);border-bottom:1px solid var(--line);
padding:calc(12px + env(safe-area-inset-top,0px)) 16px 12px}
h1{margin:0;font-size:17px;letter-spacing:.2px}
header .sub{margin:4px 0 0;color:var(--mut);font-size:12px}
main{padding:16px}
.view{display:none}.view.on{display:block}
.viewhead{margin:0 0 4px;font-size:20px}
.viewq{margin:0 0 16px;color:var(--mut);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:14px;margin:0 0 12px}
.card h2{margin:0 0 8px;font-size:15px;font-weight:600}
.card.ok{border-left:3px solid var(--ok)}
.card.warn{border-left:3px solid var(--warn)}
.card.unknown{border-left:3px solid var(--unk)}
.card.disabled{opacity:.72;border-style:dashed}
td.never{color:var(--red);font-weight:600;letter-spacing:.4px}
td.blocked{color:var(--warn);letter-spacing:.4px}
.note{margin:6px 0 0;color:var(--mut);font-size:12px}
.muted{color:var(--mut)}
.kvs{display:flex;flex-direction:column;gap:6px}
.kv{display:flex;justify-content:space-between;gap:12px;align-items:baseline;
border-bottom:1px dashed var(--line);padding-bottom:5px}
.kv:last-child{border-bottom:0;padding-bottom:0}
.kv .k{color:var(--mut);font-size:13px}
.kv .v{font-variant-numeric:tabular-nums;text-align:right;word-break:break-word}
.modes{display:grid;grid-template-columns:1fr;gap:6px}
.mode{display:flex;justify-content:space-between;background:#12151b;
border:1px solid var(--line);border-radius:10px;padding:9px 11px}
.mode .k{color:var(--mut);font-size:13px;letter-spacing:.4px}
.mode .v{font-variant-numeric:tabular-nums}
.mode.nil .v{color:var(--unk);font-style:italic}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 8px}
.chip{background:#12151b;border:1px solid var(--line);border-radius:999px;
padding:4px 10px;font-size:12px;color:var(--mut)}
.chip b{color:var(--fg);font-variant-numeric:tabular-nums}
.chip.red{border-color:#5a1f1c;color:#ffb4ae}
table{width:100%;border-collapse:collapse;font-size:13px;display:block;overflow-x:auto}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);
white-space:nowrap}
th{color:var(--mut);font-weight:500;font-size:12px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr.no td:nth-child(2){color:var(--unk)}
tr.yes td:nth-child(2){color:var(--ok)}
ul{margin:0;padding-left:18px}li{margin:0 0 5px}
.create{display:flex;align-items:center;gap:10px}
.plus{width:34px;height:34px;border-radius:999px;border:1px dashed var(--line);
display:grid;place-items:center;font-size:20px;color:var(--mut)}
.createlabel{font-size:16px;font-weight:600;color:var(--mut)}
.badge{margin-left:auto;font-size:11px;letter-spacing:.6px;color:var(--warn);
border:1px solid var(--warn);border-radius:6px;padding:2px 7px}
h3{margin:14px 0 6px;font-size:13px;font-weight:600;color:var(--mut);
letter-spacing:.3px;text-transform:uppercase}
.lead{margin:8px 0;font-size:14px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(96px,1fr));gap:8px;
margin:0 0 10px}
.stat{background:#12151b;border:1px solid var(--line);border-radius:10px;padding:8px 10px;
display:flex;flex-direction:column;gap:2px}
.stat.ok{border-left:3px solid var(--ok)}
.stat.warn{border-left:3px solid var(--warn)}
.stat.unknown{border-left:3px solid var(--unk)}
.statv{font-size:17px;font-variant-numeric:tabular-nums;word-break:break-word}
.statc{font-size:11px;color:var(--mut);line-height:1.3}
.spark{width:100%;height:64px;display:block;margin:4px 0 2px}
.spark .line{fill:none;stroke:var(--acc);stroke-width:1.6;vector-effect:non-scaling-stroke}
.spark .fill{fill:var(--acc);opacity:.13}
.spark .zero{stroke:var(--unk);stroke-width:1;stroke-dasharray:3 3;
vector-effect:non-scaling-stroke}
.bars{display:flex;flex-direction:column;gap:4px;margin:0 0 8px}
.bar{display:grid;grid-template-columns:minmax(72px,34%) 1fr auto;gap:8px;
align-items:center;font-size:12px}
.barname{color:var(--mut);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bartrack{background:#12151b;border:1px solid var(--line);border-radius:999px;height:9px;
overflow:hidden}
.barfill{display:block;height:100%;background:var(--acc);opacity:.75}
.barval{font-variant-numeric:tabular-nums;min-width:38px;text-align:right}
details.drill{margin:8px 0 0;border-top:1px dashed var(--line);padding-top:8px}
details.drill>summary{cursor:pointer;font-size:12px;color:var(--acc);list-style:none}
details.drill>summary::-webkit-details-marker{display:none}
details.drill>summary::before{content:"▸ ";color:var(--mut)}
details.drill[open]>summary::before{content:"▾ "}
.stages{display:flex;flex-direction:column;gap:6px}
.stage{display:grid;grid-template-columns:1fr auto;gap:4px 8px;background:#12151b;
border:1px solid var(--line);border-left-width:3px;border-radius:10px;padding:8px 10px}
.stage .stname{font-size:13px;font-weight:600}
.stage .stbadge{font-size:10px;letter-spacing:.5px;color:var(--mut);align-self:center}
.stage .stbasis{grid-column:1/-1;font-size:11px;color:var(--mut);line-height:1.4}
.st-live{border-left-color:var(--ok)}
.st-partial{border-left-color:var(--warn)}
.st-documented_only{border-left-color:var(--unk)}
.st-not_found,.st-unknown{border-left-color:var(--unk)}
tr.sev-critical td:first-child{color:var(--red);font-weight:600}
tr.sev-warning td:first-child,tr.sev-warn td:first-child{color:var(--warn)}
nav{position:fixed;left:0;right:0;bottom:0;z-index:6;display:grid;
grid-template-columns:repeat(3,1fr);background:rgba(18,21,27,.97);
backdrop-filter:blur(10px);border-top:1px solid var(--line);
padding-bottom:env(safe-area-inset-bottom,0px)}
nav a{display:flex;flex-direction:column;align-items:center;justify-content:center;
gap:2px;height:var(--tab);color:var(--mut);text-decoration:none;font-size:11px;
letter-spacing:.6px}
nav a .ico{font-size:19px;line-height:1}
nav a[aria-current="page"]{color:var(--acc)}
footer{padding:8px 16px 20px;color:var(--unk);font-size:11px}
@media (min-width:820px){
  body{padding-bottom:0}
  nav{position:sticky;top:0;bottom:auto;grid-template-columns:repeat(3,max-content);
      gap:4px;border-top:0;border-bottom:1px solid var(--line);padding:6px 16px}
  nav a{flex-direction:row;height:40px;gap:8px;padding:0 14px;border-radius:999px;
        font-size:13px}
  nav a[aria-current="page"]{background:#1b2331}
  main{max-width:1080px;margin:0 auto;padding:24px 16px}
  .modes{grid-template-columns:repeat(3,1fr)}
  .stats{grid-template-columns:repeat(auto-fit,minmax(120px,1fr))}
  .spark{height:96px}
  .stage{grid-template-columns:220px auto 1fr}
  .stage .stbasis{grid-column:auto}
  table{display:table}
  th,td{white-space:normal}
}
@media (prefers-color-scheme:light){
  :root{--bg:#f6f7f9;--card:#fff;--line:#e2e5ea;--fg:#14161a;--mut:#5b6472;--unk:#8b94a3}
  header{background:rgba(246,247,249,.94)}
  nav{background:rgba(255,255,255,.97)}
  .mode,.chip,.stat,.bartrack,.stage{background:#f1f3f6}
  nav a[aria-current="page"]{background:#e7effb}
}
"""

JS = """
(function(){
  var ids=['capital','studio','build'];
  function show(id){
    if(ids.indexOf(id)<0){id='capital';}
    ids.forEach(function(k){
      var v=document.getElementById('view-'+k);
      if(v){v.classList.toggle('on',k===id);}
      var t=document.getElementById('tab-'+k);
      if(t){if(k===id){t.setAttribute('aria-current','page');}
            else{t.removeAttribute('aria-current');}}
    });
    document.title=id.toUpperCase()+' · Director OS';
    window.scrollTo(0,0);
  }
  window.addEventListener('hashchange',function(){show(location.hash.slice(1));});
  show(location.hash.slice(1)||'capital');
})();
"""


def manifest(name='Director OS', short='Director'):
    """Манифест PWA. Офлайн-кеша данных нет — service worker не объявляется намеренно."""
    return {
        'name': name,
        'short_name': short,
        'description': 'Закрытый кокпит владельца: капитал, студия, разработка. Только чтение.',
        'start_url': './index.html',
        'scope': './',
        'display': 'standalone',
        'orientation': 'portrait',
        'background_color': '#0f1115',
        'theme_color': '#0f1115',
        'icons': [{'src': f'./{ICON_FILE}', 'sizes': 'any', 'type': 'image/svg+xml',
                   'purpose': 'any maskable'}],
    }


ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="108" fill="#0f1115"/>
<g fill="none" stroke="#58a6ff" stroke-width="26" stroke-linecap="round">
<path d="M136 356h240"/><path d="M160 356V236"/><path d="M256 356V196"/>
<path d="M352 356V268"/></g>
<circle cx="256" cy="150" r="22" fill="#58a6ff"/>
</svg>"""


FRESHNESS_LABELS = (
    ('last_check', 'последняя проверка'),
    ('last_successful_build', 'последняя удачная сборка'),
    ('last_semantic_change', 'последнее изменение смысла'),
    ('last_successful_publish', 'последняя удачная выкладка'),
)


def render_freshness(state):
    """Четыре времени, и ни одно не подменяет другое.

    Главная ловушка, которую этот блок обязан не допустить: «HTML не перевыкладывали»
    читается как «данные устарели». Это разные утверждения. Совпавший дайджест означает,
    что менять было нечего, — то есть кокпит свеж, а не протух.
    """
    if not state:
        return _card('Свежесть', '<p class="muted">не измерено: состояние свежести '
                                 'в сборку не подавали</p>', tone='unknown')
    rows = ''.join(
        f'<div class="kv"><span class="k">{e(label)}</span>'
        f'<span class="v">{e(_stamp(state.get(key)))}</span></div>'
        for key, label in FRESHNESS_LABELS)
    return _card('Свежесть', f'<div class="kvs">{rows}</div>',
                 note=e(state.get('unchanged_is_not_stale') or ''))


def _stamp(value):
    """Отметка времени для человека. Отсутствие — «не измерено», не пустота."""
    if not value:
        return 'не измерено'
    return str(value).replace('T', ' ')[:19] + ' UTC'


def shell_html(projection, *, architect=None, cio=None, bridge=None, generated_at=None,
               freshness=None):
    """Одна страница, три вида. Ничего не грузится из сети."""
    layers = projection.get('layers') or {}
    stamp = generated_at or projection.get('generated_at') or ''
    bodies = {
        'capital': render_freshness(freshness) + render_capital(layers.get('CAPITAL') or {}),
        'studio': render_studio(layers.get('STUDIO') or {}, architect, cio, bridge),
        'build': render_build(layers.get('BUILD') or {},
                              work=(layers.get('STUDIO') or {}).get('work')),
    }
    views = ''.join(
        f'<div class="view" id="view-{slug}">'
        f'<h2 class="viewhead">{icon} {e(title)}</h2>'
        f'<p class="viewq">{e(question)}</p>{bodies[slug]}</div>'
        for slug, title, icon, question in LAYERS)
    tabs = ''.join(
        f'<a id="tab-{slug}" href="#{slug}"><span class="ico">{icon}</span>{e(title)}</a>'
        for slug, title, icon, _q in LAYERS)
    digest = projection.get('semantic_digest') or ''
    stats = projection.get('redaction_stats') or {}
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,'
        'viewport-fit=cover">'
        '<meta name="robots" content="noindex,nofollow,noarchive">'
        '<meta name="referrer" content="no-referrer">'
        '<meta name="theme-color" content="#0f1115">'
        '<meta name="apple-mobile-web-app-capable" content="yes">'
        '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
        '<meta name="apple-mobile-web-app-title" content="Director OS">'
        f'<link rel="manifest" href="./{MANIFEST_FILE}">'
        f'<link rel="apple-touch-icon" href="./{ICON_FILE}">'
        f'<link rel="icon" type="image/svg+xml" href="./{ICON_FILE}">'
        '<title>CAPITAL · Director OS</title>'
        f'<style>{CSS}</style></head><body>'
        '<header><h1>🏛 Director OS</h1>'
        f'<p class="sub">закрытый кокпит владельца · ТОЛЬКО ЧТЕНИЕ · собрано {e(stamp)}</p>'
        '</header>'
        f'<nav aria-label="Слои Director OS">{tabs}</nav>'
        f'<main>{views}</main>'
        '<footer>Производная проекция, не источник правды. '
        f'Отпечаток проекции {e(digest)}. '
        f'Как есть {e(stats.get("SAFE_FOR_PRIVATE_WEB"))} · '
        f'отредактировано {e(stats.get("REDACTED"))} · '
        f'только локально {e(stats.get("LOCAL_ONLY"))} · '
        f'не опубликовано как UNKNOWN {e(stats.get("UNKNOWN_BLOCKED"))}.'
        '</footer>'
        f'<script>{JS}</script></body></html>')


class ShellError(Exception):
    pass


def validate_shell(page, where):
    """Контракт оболочки. Отказывает, а не чинит."""
    def need(cond, message):
        if not cond:
            raise ShellError(f'{where}: {message}')

    need('<button' not in page, 'в Epic 1 не может быть ни одного <button>')
    need('<form' not in page, 'в Epic 1 не может быть ни одной <form>')
    need('onclick=' not in page, 'обработчиков нажатия быть не должно')
    for bad in ('fetch(', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'sendBeacon'):
        need(bad not in page, f'сетевой вызов в оболочке: {bad}')
    need('src="http' not in page and 'href="http' not in page,
         'внешняя ссылка: оболочка обязана быть самодостаточной')
    need('serviceWorker' not in page,
         'service worker не объявляется, пока офлайн-модель для приватных данных не определена')
    for slug, _t, _i, _q in LAYERS:
        need(f'id="view-{slug}"' in page, f'нет вида {slug}')
        need(f'href="#{slug}"' in page, f'нет вкладки {slug}')
    need(page.count('class="view"') == len(LAYERS),
         'видов обязано быть ровно три — слои это граница, а не список')
    need('ПОКА НЕ ВКЛЮЧЕНО' in page, '«Создать» обязан быть помечен как невключённый')
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--projection', required=True,
                    help='director_web_projection.json (web-safe слой)')
    ap.add_argument('--architect', help='JSON: наблюдённое состояние Архитектора')
    ap.add_argument('--cio', help='JSON: наблюдённое состояние CIO')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)

    src = Path(args.projection)
    final = Path(args.output)
    if final.exists():
        raise SystemExit(f'{final} уже существует; каждый прогон пишет новый каталог')

    projection = json.loads(src.read_text(encoding='utf-8'))
    load = lambda raw: (json.loads(raw) if raw else None)  # noqa: E731
    bridge = (projection.get('layers', {}).get('BUILD') or {}).get('bridge')
    try:
        page = shell_html(projection, architect=load(args.architect), cio=load(args.cio),
                          bridge=bridge if isinstance(bridge, dict) else None)
        validate_shell(page, 'freshly built')
    except (ShellError, ValueError) as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\nОболочка не собрана.')

    diff_mod.validate_output(final, [src.parent])
    staging = final.with_name(final.name + '.incomplete')
    if staging.exists():
        raise SystemExit(f'{staging} остался от прерванного прогона; отодвиньте его')
    staging.mkdir(parents=True, mode=0o700)
    (staging / SHELL_FILE).write_text(page, encoding='utf-8')
    (staging / MANIFEST_FILE).write_text(
        json.dumps(manifest(), ensure_ascii=False, indent=1), encoding='utf-8')
    (staging / ICON_FILE).write_text(ICON_SVG, encoding='utf-8')
    for name in (SHELL_FILE, MANIFEST_FILE, ICON_FILE):
        os.chmod(staging / name, 0o600)
    os.rename(staging, final)

    print(f'Оболочка → {final / SHELL_FILE}')
    print(f'  размер страницы: {len(page.encode("utf-8"))} байт · манифест и иконка рядом')
    print('  кнопок действия: 0 · форм: 0 · сетевых вызовов: 0 · service worker: нет')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
