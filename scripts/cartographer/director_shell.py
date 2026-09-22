#!/usr/bin/env python3
"""Director OS v1.3 · Оболочка владельца, собранная из фактов.

Отрисовка НИЧЕГО не считает
===========================
Каждое число приходит готовым фактом с паспортом: источник, формула, свежесть, режим,
вид наблюдения. Экран лишь раскладывает их и показывает то, что факт о себе объявил.
Ровно поэтому «откуда это число» больше не вопрос к автору страницы.

Что исправлено на экране
========================
* «Просадка» больше не одно слово на две величины: ТЕКУЩАЯ и МАКСИМАЛЬНАЯ разведены,
  и у максимальной подписано, что она считается по подтверждённой серии.
* График эквити строится ПО КАЛЕНДАРЮ: пропущенные дни остаются пробелами, а
  непроверенный участок до якоря нарисован отдельно и подписан.
* Валюта подписана вместе с местом объявления.
* Возраст данных стоит рядом с числом, а не в подвале.
* Тревога о протоколе, которого нет в портфеле, живёт в наблюдении R&D, а не во
  «внимании по портфелю».
* «LIVE» больше не зелёное: рядом стоят работающие сейчас и неприменимость вопроса
  к расписанным заданиям.

Ни кнопок, ни форм, ни сети. Только stdlib.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

try:
    from . import web_shell as WS
    from . import owner_facts as F
except ImportError:
    import web_shell as WS
    import owner_facts as F

e, _num, _card, _details, _bars, _kv = (
    WS.e, WS._num, WS._card, WS._details, WS._bars, WS._kv)


def _stat(value, caption, *, tone=''):
    """Крупное число и подпись.

    Значение вставляется КАК РАЗМЕТКА намеренно: его собирает только код этого
    модуля (`_money_compact`), пользовательских строк в нём нет. Подпись при этом
    экранируется как обычно.
    """
    return (f'<div class="stat {tone}"><span class="statv">{value}</span>'
            f'<span class="statc">{e(caption)}</span></div>')


def _stats(items):
    return ('<div class="stats">'
            + ''.join(_stat(v, c, tone=t) for v, c, t in items) + '</div>')
_counter_row, _pct, _money = WS._counter_row, WS._pct, WS._money

#: Дополнение к стилю v1.2: только новые классы, ничего не переопределяется.
CSS_V13 = """
.factline{display:flex;flex-wrap:wrap;gap:.35rem;align-items:baseline;
 font-size:.78rem;line-height:1.45;color:var(--muted);margin:.15rem 0 .5rem}
.cur{font-size:.55em;opacity:.7;margin-left:.28em;letter-spacing:.02em}
.card .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(9.5rem,1fr));gap:.5rem}
@media(max-width:560px){.card .stats{grid-template-columns:1fr 1fr}}
.stat .statv{overflow-wrap:normal;word-break:keep-all}
.factline .src{font-family:ui-monospace,Menlo,monospace}
.tag{display:inline-block;padding:.05rem .4rem;border-radius:.4rem;font-size:.72rem;
 border:1px solid var(--line);white-space:nowrap}
.tag.obs{border-color:#2e7d5b;color:#7fdcb0}
.tag.der{border-color:#4a5a78;color:#9dbbe8}
.tag.tgt{border-color:#7a5c2e;color:#e8c98a}
.tag.shadow{border-color:#5d4a78;color:#c3a8e8}
.tag.stale{border-color:#8a4a2e;color:#f0a67c}
.tag.unver{border-color:#6a5a2e;color:#ddc98a}
.tag.conflict{border-color:#8a2e3e;color:#f09aa8}
.eqchart{width:100%;height:180px;display:block}
.eqchart .evid{fill:none;stroke:#5fb98a;stroke-width:1.6}
.eqchart .unver{fill:none;stroke:#8a7a4a;stroke-width:1.4;stroke-dasharray:3 3}
.eqchart .gapmark{stroke:#8a4a2e;stroke-width:1;stroke-dasharray:2 3}
.eqchart .bnd{stroke:#a8455c;stroke-width:1.2;stroke-dasharray:4 3}
.eqchart .ax{stroke:var(--line);stroke-width:1}
.eqchart text{fill:var(--muted);font-size:9px}
.legend{display:flex;flex-wrap:wrap;gap:.6rem;font-size:.74rem;color:var(--muted);
 margin:.3rem 0}
.legend i{display:inline-block;width:14px;height:0;border-top-width:2px;
 border-top-style:solid;vertical-align:middle;margin-right:.25rem}
.attn{border-left:3px solid #8a4a2e;padding:.4rem .6rem;margin:.4rem 0;
 background:rgba(138,74,46,.08);border-radius:.3rem}
.attn.decide{border-left-color:#a8455c;background:rgba(168,69,92,.10)}
.attn h4{margin:0 0 .2rem;font-size:.82rem}
.split{display:grid;grid-template-columns:1fr 1fr;gap:.6rem}
@media(max-width:560px){.split{grid-template-columns:1fr}
 /* На телефоне мелкий шрифт перестаёт читаться, а не просто мельчает. Пол в 12px
    объявлен здесь по замеру первого визуального прохода: 60 элементов оказались
    мельче 11px, и подпись факта превращалась в узор. */
 .factline,.tag,.legend,.cmp .hd,.stagerow .n,.stagerow .ev{font-size:12px}
 .stat .statv{font-size:1.05rem}}
.cmp{display:grid;grid-template-columns:1fr auto auto;gap:.25rem .5rem;
 font-size:.78rem;align-items:center}
.cmp .hd{font-size:.74rem;color:var(--muted);text-transform:uppercase;
 letter-spacing:.04em}
.stagerow{display:grid;grid-template-columns:1.6rem 1fr auto;gap:.4rem;
 align-items:baseline;padding:.25rem 0;border-bottom:1px solid var(--line)}
.stagerow:last-child{border-bottom:0}
.stagerow .n{color:var(--muted);font-size:.78rem}
.stagerow .ev{font-size:.76rem;color:var(--muted);grid-column:2/4;margin:0 0 .2rem}
"""

#: Как называется вид наблюдения на экране. Слово «текущее» не даётся ничему,
#: что текущим не является.
KIND_LABEL = {
    'CURRENT_OBSERVED': ('наблюдение', 'obs'),
    'TARGET_POLICY': ('цель по политике', 'tgt'),
    'SHADOW_PROPOSED': ('теневое предложение', 'shadow'),
    'HISTORICAL': ('история', 'obs'),
    'CONFIGURED': ('настроено', 'tgt'),
    'EXPECTED': ('ожидание', 'tgt'),
    'UNKNOWN': ('вид не объявлен', ''),
}

#: Важность словами. Словарь источника остаётся в раскрытии — он улика, а не речь.
SEVERITY_WORD = {
    'DECLARED_NON_COMPLIANT': 'портфель объявлен не соответствующим политике',
    'CRITICAL': 'критично', 'WARN': 'предупреждение', 'INFO': 'к сведению',
}

FRESH_LABEL = {'FRESH': 'свежо', 'AGING': 'стареет', 'STALE': 'протухло',
               'NOT_MEASURED': 'свежесть не измерена', 'TIMELESS': 'не устаревает'}


def _counters(mapping, *, limit=10):
    """Счётчики, где «не измерено» НЕ сортируется как ноль и не подаётся числом.

    Помощник v1.2 сортировал по ``-(значение or 0)``: `None` вставал между нулём и
    единицей, а вложенный словарь ронял сортировку целиком. Здесь числа и «не измерено»
    разведены, и второе показывается словами, а не позицией в ряду.
    """
    if not mapping:
        return '<p class="muted">не измерено</p>'
    numeric, unmeasured = [], []
    for key, value in mapping.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            unmeasured.append(key)
        else:
            numeric.append((key, value))
    numeric.sort(key=lambda kv: (-kv[1], kv[0]))
    chips = ''.join(f'<span class="chip"><b>{e(_num(v))}</b> {e(k)}</span>'
                    for k, v in numeric[:limit])
    if unmeasured:
        chips += ''.join(f'<span class="chip"><b>не измерено</b> {e(k)}</span>'
                         for k in sorted(unmeasured)[:limit])
    return f'<div class="chips">{chips}</div>' if chips else '<p class="muted">не измерено</p>'


def _days(value):
    """Дни по-русски. «93.01 дней» — это вывод прибора, а не фраза для человека."""
    if value is None:
        return 'возраст не объявлен'
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return str(value)
    tail = n % 100
    if 11 <= tail <= 14:
        word = 'дней'
    elif n % 10 == 1:
        word = 'день'
    elif n % 10 in (2, 3, 4):
        word = 'дня'
    else:
        word = 'дней'
    return f'{n} {word}'


def _age_words(hours):
    if hours is None:
        return 'возраст не измерен'
    if hours < 1:
        return f'{int(hours * 60)} мин назад'
    if hours < 48:
        return f'{hours:.1f} ч назад'
    return f'{hours / 24:.1f} сут назад'


def _fact_tags(f):
    """Ярлыки факта: вид наблюдения, вывод/наблюдение, свежесть, конфликт."""
    out = []
    label, cls = KIND_LABEL.get(f.get('observation_kind') or 'UNKNOWN', ('', ''))
    if label:
        out.append(f'<span class="tag {cls}">{e(label)}</span>')
    if f.get('fact_kind') == 'DERIVED':
        out.append('<span class="tag der">выведено</span>')
    state = f.get('freshness_state')
    if state in ('STALE', 'AGING'):
        out.append(f'<span class="tag stale">{e(FRESH_LABEL.get(state, state))}</span>')
    if state == 'NOT_MEASURED':
        out.append('<span class="tag unver">свежесть не измерена</span>')
    if f.get('verification_state') == 'CONFLICT':
        out.append('<span class="tag conflict">расхождение источников</span>')
    if f.get('caveat'):
        out.append('<span class="tag unver">с оговоркой</span>')
    return ''.join(out)


def _fact_line(f):
    """Паспорт факта под числом.

    На главном экране остаётся то, что владелец читает глазами: вид наблюдения и
    возраст. Путь к полю и формула уходят в раскрытие — это ответ на вопрос «откуда»,
    и он обязан быть доступен, но не обязан занимать главный экран. Первый визуальный
    проход показал строку `data/current_positions.json:current_equity_usd` моноширинным
    шрифтом во всю ширину телефона прямо под суммой.
    """
    head = [_fact_tags(f)]
    if f.get('freshness_state') != 'TIMELESS':
        head.append(e(_age_words(f.get('freshness_age_hours'))))
    else:
        head.append('решение, а не замер')
    inner = [f'<div class="kv"><span class="k">источник</span>'
             f'<span class="v src">{e(f.get("source") or "не назван")}'
             + (f':{e(f["source_field"])}' if f.get('source_field') else '')
             + '</span></div>']
    if f.get('derivation'):
        inner.append(f'<div class="kv"><span class="k">формула</span>'
                     f'<span class="v">{e(f["derivation"])}</span></div>')
    if f.get('currency') and f.get('currency_basis'):
        inner.append(f'<div class="kv"><span class="k">валюта</span>'
                     f'<span class="v">{e(f["currency"])} объявлена в '
                     f'{e(f["currency_basis"])}</span></div>')
    if f.get('observed_at'):
        inner.append(f'<div class="kv"><span class="k">наблюдено</span>'
                     f'<span class="v">{e(_human_stamp(f["observed_at"]))}</span></div>')
    return (f'<p class="factline">' + ' · '.join(x for x in head if x) + '</p>'
            + _details('откуда это число', '<div class="kvs">' + ''.join(inner) + '</div>'))


def _money_compact(value, currency):
    """Деньги, которые помещаются в карточку.

    Первый визуальный проход: «101 340.69 USDC» вставало в ТРИ строки на 390 px, и
    владелец читал сумму по слогам. Хвост «.00» уносится — он ничего не добавляет;
    разряды делятся тонким неразрывным пробелом; валюта уходит в отдельный мелкий
    знак, потому что она подпись к числу, а не часть числа.
    """
    if value is None:
        return 'не измерено'
    try:
        num = float(value)
    except (TypeError, ValueError):
        return e(str(value))
    body = f'{num:,.2f}'.replace(',', '\u202f')
    if body.endswith('.00'):
        body = body[:-3]
    if not currency:
        return body
    return body + f'<span class="cur">{e(currency)}</span>'


def _fact_value(f, *, digits=2, money=False):
    if f.get('value') is None:
        return 'не измерено'
    v = f['value']
    if isinstance(v, bool):
        return 'да' if v else 'НЕТ'
    if money:
        return _money_compact(v, f.get('currency'))
    if f.get('unit') == '%':
        return _pct(v, digits)
    try:
        return f'{float(v):,.{digits}f}'.replace(',', ' ').rstrip('0').rstrip('.')
    except (TypeError, ValueError):
        return str(v)


def _by_metric(facts):
    return {f['metric']: f for f in facts}


# ── График эквити по КАЛЕНДАРЮ ────────────────────────────────────────────────

def equity_chart(points, *, quality, width=640, height=180):
    """Ось X — календарь, а не номер точки.

    v1.2 рисовала 121 точку равномерно, поэтому два пропущенных дня выглядели
    соседними. Здесь пропуск остаётся пробелом и помечается, а участок до якоря
    рисуется пунктиром: непроверенная история и подтверждённая — разные вещи, и
    линия обязана это показывать.
    """
    rows = [(r.get('date'), r.get('close_equity'), bool(r.get('evidenced')))
            for r in points or ()]
    rows = [(d, v, ev) for d, v, ev in rows if d and isinstance(v, (int, float))]
    if len(rows) < WS.CHART_MIN_POINTS:
        return (f'<p class="muted">график не строится: точек {len(rows)}, нужно от '
                f'{WS.CHART_MIN_POINTS}</p>')
    parsed = []
    for d, v, ev in rows:
        try:
            parsed.append((date.fromisoformat(str(d)[:10]), v, ev))
        except ValueError:
            continue
    parsed.sort(key=lambda p: p[0])
    first, last = parsed[0][0], parsed[-1][0]
    span_days = (last - first).days or 1
    lo = min(v for _d, v, _e in parsed)
    hi = max(v for _d, v, _e in parsed)
    vspan = (hi - lo) or 1.0
    pad_l, pad_b = 6, 14

    def xy(d, v):
        x = pad_l + (d - first).days / span_days * (width - pad_l * 2)
        y = (height - pad_b) - (v - lo) / vspan * (height - pad_b - 8)
        return x, y

    missing = set(quality.get('missing_dates') or ())
    boundaries = set(quality.get('series_boundaries') or ())

    # Ломаная режется на куски: на пропуске и на разрыве серии линия не продолжается.
    segments, current, current_ev = [], [], None
    prev_d = None
    for d, v, ev in parsed:
        cut = False
        if prev_d is not None:
            gap = [(prev_d.toordinal() + i) for i in range(1, (d - prev_d).days)]
            if any(date.fromordinal(g).isoformat() in missing for g in gap):
                cut = True
        if d.isoformat() in boundaries or ev != current_ev:
            cut = True
        if cut and current:
            segments.append((current_ev, current))
            current = [current[-1]] if (ev == current_ev and d.isoformat() not in boundaries) else []
        current.append(xy(d, v))
        current_ev = ev
        prev_d = d
    if current:
        segments.append((current_ev, current))

    paths = ''.join(
        f'<polyline class="{"evid" if ev else "unver"}" points="'
        + ' '.join(f'{x:.1f},{y:.1f}' for x, y in pts) + '"/>'
        for ev, pts in segments if len(pts) >= 2)
    marks = ''.join(
        f'<line class="gapmark" x1="{pad_l + (date.fromisoformat(m) - first).days / span_days * (width - pad_l * 2):.1f}"'
        f' y1="8" x2="{pad_l + (date.fromisoformat(m) - first).days / span_days * (width - pad_l * 2):.1f}"'
        f' y2="{height - pad_b}"/>'
        for m in sorted(missing) if first <= date.fromisoformat(m) <= last)
    bnds = ''.join(
        f'<line class="bnd" x1="{pad_l + (date.fromisoformat(b) - first).days / span_days * (width - pad_l * 2):.1f}"'
        f' y1="4" x2="{pad_l + (date.fromisoformat(b) - first).days / span_days * (width - pad_l * 2):.1f}"'
        f' y2="{height - pad_b}"/>'
        for b in sorted(boundaries) if first <= date.fromisoformat(b) <= last)
    axis = (f'<line class="ax" x1="{pad_l}" y1="{height - pad_b}" x2="{width - pad_l}" '
            f'y2="{height - pad_b}"/>')
    labels = (f'<text x="{pad_l}" y="{height - 3}">{e(first.isoformat())}</text>'
              f'<text x="{width - pad_l}" y="{height - 3}" text-anchor="end">'
              f'{e(last.isoformat())}</text>')
    return (f'<svg class="eqchart" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="эквити по календарю с {e(first.isoformat())} по '
            f'{e(last.isoformat())}" preserveAspectRatio="none">'
            f'{axis}{bnds}{marks}{paths}{labels}</svg>'
            '<div class="legend">'
            '<span><i style="border-color:#5fb98a"></i>подтверждённая история</span>'
            '<span><i style="border-color:#8a7a4a;border-top-style:dashed"></i>'
            'непроверенная (до якоря)</span>'
            '<span><i style="border-color:#8a4a2e;border-top-style:dashed"></i>'
            'пропущенный день</span>'
            '<span><i style="border-color:#a8455c;border-top-style:dashed"></i>'
            'разрыв ряда</span></div>')


# ── CAPITAL ───────────────────────────────────────────────────────────────────

def render_capital(cap, *, layer=None):
    """Четыре вопроса сверху: что есть · что изменилось · вне ли политики · что ждёт меня."""
    if not cap or cap.get('schema') is None:
        return _card('Капитал', '<p class="muted">набор фактов не собран — это НЕ значит, '
                                'что капитала нет</p>', tone='unknown')
    m = _by_metric(cap['facts'])
    q = cap.get('history_quality') or {}
    attention = cap.get('attention') or {}
    out = []

    # 1. ЧТО У МЕНЯ ЕСТЬ
    eq = m.get('equity_now') or {}
    body = _stats([
        (_fact_value(eq, money=True), 'эквити сейчас', ''),
        (_fact_value(m.get('deployed_usd') or {}, money=True), 'вложено', ''),
        (_fact_value(m.get('cash_usd') or {}, money=True), 'в кэше', ''),
        (_fact_value(m.get('net_pnl_usd') or {}, money=True), 'чистый P&L', ''),
    ]) + _fact_line(eq)
    body += _stats([
        (_fact_value(m.get('accrued_yield_usd') or {}, money=True), 'накопленный доход', ''),
        (_fact_value(m.get('costs_paid_usd') or {}, money=True), 'уплачено издержек', ''),
        (_fact_value(m.get('apy_portfolio_current') or {}), 'APY портфеля сейчас', ''),
        (_fact_value(m.get('apy_expected') or {}), 'APY ожидаемый', ''),
    ])
    dep = m.get('deployed_usd') or {}
    if dep.get('verification_state') == 'VERIFIED':
        body += ('<p class="note">«вложено» объявлено источником и сошлось с независимой '
                 'суммой позиций</p>')
    elif dep.get('verification_state') == 'CONFLICT':
        c = (dep.get('conflicts') or [{}])[0]
        body += (f'<p class="note">РАСХОЖДЕНИЕ: источник объявляет '
                 f'{e(_num(c.get("declared_value")))}, независимая сумма позиций — '
                 f'{e(_num(c.get("other_value")))}. Показано и то, и другое: выбор '
                 f'источника — решение архитектуры, а не экрана</p>')
    real_note = (layer or {}).get('real_capital_headline') or 'REAL CAPITAL: NOT PROVEN'
    body += (f'<p class="note"><b>{e(real_note)}</b> — ни один источник не объявил режим '
             f'настоящих денег. Режим этих чисел: {e(cap.get("mode"))}. '
             f'Валюта {e(cap.get("currency") or "не объявлена")}'
             + (f' (объявлена в {e(cap["currency_basis"])})' if cap.get('currency_basis') else '')
             + '</p>')
    out.append(_card('Что у меня есть', body))

    # 2. ЧТО ИЗМЕНИЛОСЬ
    wins = []
    for metric, cap_word in (('return_1d', 'за день'), ('return_7d', 'за 7 дней'),
                             ('return_30d', 'за 30 дней'),
                             ('return_since_evidenced_start', 'с якоря')):
        f = m.get(metric) or {}
        word = cap_word
        win = f.get('window') or {}
        actual = win.get('window_actual_days')
        req = win.get('window_requested_days')
        if actual and req and actual != req:
            word = f'{cap_word} (факт. {actual} дн.)'
        wins.append((_fact_value(f, digits=4), word, ''))
    body = _stats(wins)
    ref = m.get('return_7d') or m.get('return_1d') or {}
    if ref:
        body += _fact_line(ref)
    avail = m.get('return_since_available_start') or {}
    if avail.get('caveat'):
        body += (f'<p class="note">За весь доступный ряд получается '
                 f'{e(_fact_value(avail, digits=4))}, но это окно включает объявленный '
                 f'разрыв ряда {e(", ".join(avail["caveat"].get("boundaries") or ()))}: '
                 f'часть «дохода» там — склейка двух серий, а не движение капитала. '
                 f'Поэтому наверху стоит доход с якоря.</p>')

    # Просадка — ДВЕ разные величины, и это сказано словами.
    cur, mx = m.get('current_drawdown') or {}, m.get('max_drawdown_evidenced') or {}
    body += ('<div class="split">'
             f'<div>{_stats([(_fact_value(cur, digits=4), "просадка СЕЙЧАС", "")])}'
             f'<p class="note">насколько мы ниже исторического пика прямо сейчас</p></div>'
             f'<div>{_stats([(_fact_value(mx, digits=4), "МАКСИМАЛЬНАЯ просадка", "")])}'
             f'<p class="note">худшее падение пик→дно по подтверждённой серии</p></div>'
             '</div>')
    if mx.get('caveat'):
        body += (f'<p class="note">Та же формула без учёта разрыва ряда даёт '
                 f'{e(_num(mx["caveat"].get("naive_value")))} %. Это не просадка: это '
                 f'ступень между разогревочной и восстановленной сериями, и источник '
                 f'сам пишет об этом в примечании той строки. Предыдущий выпуск '
                 f'показывал именно её.</p>')
    out.append(_card('Что изменилось', body))

    # 3. ВНЕ ЛИ ПОЛИТИКИ — три РАЗНЫХ вопроса, разведённых явно
    pol = cap.get('policy') or {}
    pf = m.get('policy_compliant') or {}
    tone = 'warn' if pf.get('value') is False else ''
    body = _stats([
        ('НЕТ' if pf.get('value') is False else _fact_value(pf),
         'соответствует политике', ''),
        ((layer or {}).get('kill_switch', {}).get('triggered') and 'СРАБОТАЛ' or 'не сработал',
         'стоп-кран', ''),
        (pol.get('policy_version') or 'не объявлено', 'версия политики', ''),
    ])
    body += _fact_line(pf) if pf else ''
    body += ('<p class="note">Это ТРИ разных вопроса: соответствие политике объявляет '
             'источник позиций; стоп-кран — отдельный механизм просадки; пороги риска — '
             'решение ADR, а не замер. Совпадать они не обязаны.</p>')
    if pol.get('state') == 'READ' and pf.get('value') is False:
        checks = pol.get('layer_checks_at_or_over') or []
        body += (f'<p class="note"><b>Причину источник НЕ объявляет.</b> '
                 f'{e(pol.get("reason_note"))}</p>')
        rows = ''.join(
            f'<div class="cmp"><span>{e(c.get("check"))}</span>'
            f'<span>{e(_num(c.get("value_pct")))}</span>'
            f'<span>{e(_num(c.get("ceiling_pct")))}</span></div>'
            for c in (pol.get('layer_checks') or []) if c.get('state') != 'NOT_MEASURED')
        body += _details(
            f'сверка кокпита с объявленными порогами — на пределе или выше: {len(checks)}',
            '<div class="cmp"><span class="hd">проверка</span><span class="hd">факт</span>'
            '<span class="hd">порог</span></div>' + rows,
            note='эта сверка принадлежит кокпиту, а не источнику. Её совпадение с '
                 'вердиктом источника НЕ доказывает, что причина именно та')
    out.append(_card('Соответствие политике', body, tone=tone))

    # 4. ЧТО ТРЕБУЕТ МОЕГО ВНИМАНИЯ
    items = attention.get('portfolio_attention') or []
    if items:
        blocks = ''
        for i in items:
            cls = 'decide' if i.get('owner_relevance') == 'DECISION_REQUIRED' else ''
            want = {'DECISION_REQUIRED': 'нужно ваше решение',
                    'ACTION_REQUIRED': 'нужно действие',
                    'INFORMATION_ONLY': 'к сведению, действий не требуется'}.get(
                        i.get('owner_relevance'), 'что требуется — не определено')
            sev = SEVERITY_WORD.get(i.get('severity'), i.get('severity'))
            blocks += (f'<div class="attn {cls}"><h4>{e(i.get("message"))}</h4>'
                       f'<p class="note">{e(want)} · {e(sev)} · '
                       f'{e(_age_words(i.get("age_hours")))}</p>'
                       + _details('откуда это',
                                  _kv([('предмет', i.get('subject')),
                                       ('важность по источнику', i.get('severity')),
                                       ('источник важности', i.get('severity_source'))]))
                       + '</div>')
        body = blocks
    else:
        body = ('<p class="muted">по портфелю ничего не требует внимания прямо сейчас. '
                'Это НЕ означает «всё здорово» — это означает, что ни одна тревога не '
                'прошла проверку относимости и свежести</p>')
    body += (f'<p class="note">{e(attention.get("admission_rule"))}</p>')
    watch = attention.get('watchlist_rnd') or []
    if watch:
        rows = ''.join(
            f'<div class="cmp"><span>{e(w.get("subject"))} — {e(w.get("message"))}</span>'
            f'<span>{e(w.get("severity"))}</span>'
            f'<span>{e({"RECENTLY_EXITED": "недавно вышли", "BLOCKED_CANDIDATE": "заблокированный кандидат"}.get(w.get("portfolio_link"), w.get("portfolio_link")))}</span></div>'
            for w in watch)
        body += _details(
            f'наблюдение R&D: {len(watch)} — протоколы ВНЕ портфеля',
            rows,
            note='эти тревоги относятся к протоколам, которых в портфеле нет. Показывать '
                 'их как «требует внимания по портфелю» было бы тревогой не о том')
    nr = attention.get('not_relevant') or []
    if nr:
        body += _details(f'связь с портфелем не доказана: {len(nr)}',
                         ''.join(f'<div class="cmp"><span>{e(x.get("subject"))}</span>'
                                 f'<span>{e(x.get("severity"))}</span><span>—</span></div>'
                                 for x in nr))
    attention_card = _card('Что требует моего решения', body,
                           tone='warn' if items else '')

    # 5. ИСТОРИЯ — график по календарю
    daily = (cap.get('series_rows') or [])
    body = equity_chart(daily, quality=q)
    body += _kv([
        ('точек в ряду', q.get('points')),
        ('подтверждено (с якоря)', q.get('evidenced_points')),
        ('непроверено (до якоря)', q.get('unverified_points')),
        ('якорь', q.get('anchor_date')),
        ('пропущено календарных дней', q.get('missing_count')),
        ('разрывов ряда', len(q.get('series_boundaries') or ())),
    ])
    if q.get('missing_dates'):
        body += (f'<p class="note">Пропущенные дни: '
                 f'{e(", ".join(q["missing_dates"]))}. Они НЕ нарисованы как соседние '
                 f'точки — на графике это пробел.</p>')
    if q.get('series_boundaries'):
        body += (f'<p class="note">{e(q.get("boundary_note"))} Разрыв: '
                 f'{e(", ".join(q["series_boundaries"]))}.</p>')
    body += _details('из чего собран ряд',
                     _counters(q.get('segments_by_source') or {}),
                     note='warmup и backfill — непроверенная история до якоря; '
                          'cycle — подтверждённые дни')
    out.append(_card('История', body))

    # 6. СЕЙЧАС против ЦЕЛИ
    pos = cap.get('positions') or []
    target = cap.get('target') or {}
    rows = ''.join(
        f'<div class="cmp"><span>{e(p["protocol"])}</span>'
        f'<span>{e(_money(p.get("usd"), cap.get("currency")))}</span>'
        f'<span>{e(_pct(p.get("share_pct"), 1))}</span></div>' for p in pos)
    body = ('<h3 class="viewq">СЕЙЧАС — наблюдение</h3>'
            '<div class="cmp"><span class="hd">протокол</span><span class="hd">сумма</span>'
            f'<span class="hd">доля</span></div>{rows}')
    ages = {p.get('apy_age_hours') for p in pos if p.get('apy_age_hours') is not None}
    if ages:
        body += (f'<p class="note">APY этих позиций наблюдался '
                 f'{e(_age_words(max(ages)))} — это возраст ДАННЫХ, а не возраст '
                 f'страницы</p>')
    if target.get('state') == 'READ':
        legs = ''.join(
            f'<div class="cmp"><span>{e(l.get("protocol"))}</span>'
            f'<span>{e(_money(l.get("delta_usd"), cap.get("currency")))}</span>'
            f'<span>{e(l.get("direction"))}</span></div>'
            for l in target.get('legs') or ())
        body += ('<h3 class="viewq">ЦЕЛЬ / ТЕНЬ — предложение, капитал не двигался</h3>'
                 + _stats([
                     (target.get('decision') or 'не объявлено', 'теневое решение', ''),
                     (_pct(target.get('apy_now_pp'), 3), 'APY сейчас', ''),
                     (_pct(target.get('apy_opt_pp'), 3), 'APY оптимума', ''),
                     (_pct(target.get('gain_pp'), 3), 'выигрыш', ''),
                 ])
                 + f'<p class="note">порог выигрыша {e(_pct(target.get("required_gain_pp"), 3))}'
                   f' · окупаемость {e(_num(target.get("payback_days")))} дн.'
                   f' · издержки перехода {e(_money(target.get("cost_usd"), cap.get("currency")))}</p>'
                 + f'<p class="note"><b>Режим {e(target.get("mode"))}.</b> '
                   f'{e(target.get("advisory_note") or "")} Ни одна доля отсюда не '
                   f'является текущей.</p>'
                 + _details(f'предлагаемые перемещения: {target.get("leg_count")}', legs)
                 + _details(f'гейты, которые не пускают переход: {len(target.get("gates_blocking") or ())} из {target.get("gates_total")}',
                            _counters({g: 1 for g in target.get('gates_blocking') or ()},
                                         limit=12)))
    else:
        body += ('<p class="muted">целевая аллокация не измерена — это НЕ значит, '
                 'что цели нет</p>')
    out.append(_card('Сейчас против цели', body))
    # Внимание владельца идёт ПЕРВЫМ: это единственная карточка, на которую он может
    # ответить действием. Остальное — справка о состоянии.
    return attention_card + ''.join(out)


#: Словарь состояний жизненного цикла слоя. Литерала по умолчанию здесь нет
#: намеренно: вердикт о том, построен ли слой, обязан приходить замером.
LIFECYCLE_STATES = ('DOCUMENTED_ONLY', 'CODE_EXISTS', 'RUNTIME_EXISTS', 'SCHEDULED',
                    'ACTIVE', 'PARTIAL', 'NOT_MEASURED')


def _lifecycle_claim(value, what):
    """Состояние слоя и, если его не измеряли, ЧЕСТНАЯ причина вместо вердикта.

    Прежняя редакция подставляла ``DOCUMENTED_ONLY`` литералом, и экран утверждал, что
    слой не построен, ничего об этом не измерив. Для CIO это утверждение оказалось
    неверным: компонент существует, у него есть расписание и артефакты.
    """
    if value in LIFECYCLE_STATES and value != 'NOT_MEASURED':
        return {'label': value, 'note': None}
    return {'label': 'НЕ ИЗМЕРЕНО',
            'note': (f'состояние «{what}» в этой сборке не измерялось. Раньше здесь '
                     f'стояло DOCUMENTED_ONLY из литерала по умолчанию — то есть экран '
                     f'утверждал, что слой не построен, не проверив этого')}


# ── STUDIO ────────────────────────────────────────────────────────────────────

#: Вердикт здоровья словами. «Слепо» — не провал и не здоровье.
HEALTH_WORD = {'HEALTHY': 'здорова', 'UNHEALTHY': 'НЕ делает своего дела',
               'BLIND': 'наблюдение есть, доверия нет', 'NOT_MEASURED': 'не измерено'}

RUNNING_WORD = {True: 'работает сейчас', False: 'резидент не работает',
                'NOT_APPLICABLE': 'вопрос неприменим', None: 'не измерено'}


def render_studio(*, health, decisions, bridge, rnd=None, layer=None,
                  measured_health=None, durability=None, classification=None,
                  roles=None):
    """Сверху — что требует внимания, что работает, что строится, что ждёт владельца.
    Список из 103 служб живёт в раскрытии, а не в начале."""
    out = []

    # 1. ЧТО ЖДЁТ ВЛАДЕЛЬЦА — первым, потому что это единственное, что он может сделать
    d = decisions or {}
    items = d.get('items') or []
    # Классы очереди из Эпика G: ждущее решения, работа системы, просроченная
    # предпосылка и неопределённое. Показывать их одним списком значило бы занимать
    # владельца чужой работой и вопросами, предпосылку которых надо перемерить.
    real = [i for i in items if i.get('item_class') == 'OWNER_DECISION_REQUIRED']
    defects = [i for i in items if i.get('item_class') == 'SYSTEM_SHOULD_RESOLVE']
    stale = [i for i in items if i.get('item_class') == 'STALE']
    unclear = [i for i in items if i.get('item_class') == 'UNKNOWN']
    if not any(i.get('item_class') for i in items):
        # Проекция старее классификации — показываем как было, не выдумывая классов.
        real = [i for i in items if i.get('subject') != 'NONE']
        defects = [i for i in items if i.get('subject') == 'NONE']
        stale, unclear = [], []
    blocks = ''.join(
        f'<div class="attn decide"><h4>{e(i.get("title_ru"))}</h4>'
        f'<p class="note">предмет {e(i.get("subject"))} — '
        f'{e(d.get("subject_vocabulary", {}).get(i.get("subject"), ""))} · '
        f'{e("ждёт " + _days(i["age_days"]) if i.get("age_days") is not None else "возраст источник не объявляет")} · '
        f'источник {e(i.get("source"))}</p></div>' for i in real[:12])
    body = blocks or '<p class="muted">ни одно решение владельца не ждёт ответа</p>'
    body += _stats([
        (len(real), 'ждёт ВАШЕГО решения', ''),
        (len(stale), 'предпосылку надо перемерить', ''),
        (len(defects), 'это работа системы', ''),
        (d.get('items_without_declared_age'), 'без объявленного возраста', ''),
    ])
    if stale:
        body += _details(
            f'предпосылку надо перемерить: {len(stale)}',
            ''.join(f'<div class="cmp"><span>{e(x.get("title_ru"))}</span>'
                    f'<span>{e(_days(x.get("age_days")))}</span>'
                    f'<span>{e(x.get("source"))}</span></div>' for x in stale),
            note='предмет владельца, но вопрос ждёт дольше объявленного порога: прежде '
                 'чем отвечать, надо проверить, стоит ли он ещё')
    if unclear:
        body += _details(f'предмет не определён: {len(unclear)}',
                         ''.join(f'<div class="cmp"><span>{e(x.get("title_ru"))}</span>'
                                 f'<span>—</span><span>{e(x.get("source"))}</span></div>'
                                 for x in unclear))
    body += f'<p class="note">{e(d.get("severity_note") or "")}</p>'
    if defects:
        body += _details(
            f'дефекты очереди: {len(defects)} — это работа агента, не решение владельца',
            ''.join(f'<div class="cmp"><span>{e(x.get("title_ru"))}</span>'
                    f'<span>{e(x.get("source"))}</span><span>—</span></div>'
                    for x in defects),
            note=d.get('queue_defect_note'))
    src_rows = ''.join(
        f'<div class="cmp"><span>{e(s.get("source"))}</span>'
        f'<span>{e(_num(s.get("waiting_count")))}</span>'
        f'<span>{e(_num(s.get("total_rows")))}</span></div>' for s in d.get('sources') or ())
    body += _details('откуда собрана очередь',
                     '<div class="cmp"><span class="hd">источник</span>'
                     '<span class="hd">ждёт</span><span class="hd">всего</span></div>'
                     + src_rows, note=d.get('identity_note'))
    out.append(_card('Что ждёт моего решения', body, tone='warn' if real else ''))

    # 2. ЧТО ТРЕБУЕТ ВНИМАНИЯ ВО ФЛОТЕ
    h = health or {}
    problems = h.get('problems') or []
    retired = h.get('problems_retired') or []
    if problems:
        rows = ''.join(
            f'<div class="cmp"><span>{e(p.get("label"))}</span>'
            f'<span>{e(p.get("problem"))}</span>'
            f'<span>{e(str(p.get("detail"))[:40])}</span></div>' for p in problems)
        body = ('<div class="cmp"><span class="hd">служба</span><span class="hd">что</span>'
                f'<span class="hd">подробность</span></div>{rows}')
    else:
        body = '<p class="muted">во флоте ничего не требует внимания</p>'
    body += (f'<p class="note">{e(h.get("last_exit_note") or "")}</p>')
    if retired:
        body += _details(f'то же у выведенных из эксплуатации: {len(retired)}',
                         ''.join(f'<div class="cmp"><span>{e(p.get("label"))}</span>'
                                 f'<span>{e(p.get("problem"))}</span><span>—</span></div>'
                                 for p in retired),
                         note='выведенная из эксплуатации служба не обязана быть свежей: '
                              'это не проблема флота')
    out.append(_card('Что требует внимания', body, tone='warn' if problems else ''))

    # 3. ЧТО СЕЙЧАС РАБОТАЕТ — без зелёного «LIVE»
    c = h.get('counts') or {}
    body = _stats([
        (c.get('running_true'), 'резидентов работает сейчас', ''),
        (c.get('running_not_applicable'), 'по расписанию (вопрос неприменим)', ''),
        (c.get('producing_true'), 'производят свежий артефакт', ''),
        (c.get('total'), 'служб всего', ''),
    ])
    # Счётчик «здоровье не измерено» отсюда убран, когда есть объявленные контракты:
    # иначе на одном экране стояли бы ДВА разных числа под одной подписью — 103 от
    # слоя, не знающего о контрактах, и 97 от того, который знает. Ровно тот дефект,
    # ради которого весь выпуск и делался.
    _health_declared = (measured_health or {}).get('declared_contracts') or 0
    _third = [(c.get('stale_output'), 'артефактов протухло', ''),
              (c.get('missing_output'), 'артефактов отсутствует', ''),
              (c.get('nonzero_last_exit'), 'ненулевой код прошлого выхода', '')]
    if not _health_declared:
        _third.append((c.get('health_not_measured'), 'здоровье НЕ измерено', ''))
    body += _stats(_third)
    body += f'<p class="note">{e(h.get("running_note") or "")}</p>'
    mh = measured_health or {}
    declared = mh.get('declared_contracts') or 0
    if declared:
        mc = mh.get('counts') or {}
        body += _stats([
            (mc.get('HEALTHY'), 'здоровы по контракту', ''),
            (mc.get('UNHEALTHY'), 'НЕ здоровы', ''),
            (mc.get('BLIND'), 'наблюдение есть, доверия нет', ''),
            ((c.get('total') or 0) - declared, 'здоровье НЕ измерено', ''),
        ])
        bad = mh.get('unhealthy') or []
        blind = mh.get('blind') or []
        if bad:
            body += ''.join(
                f'<div class="attn"><h4>{e(lbl.split(".")[-1])} — не делает своего дела'
                f'</h4><p class="note">'
                + e(next((ch['why'] for ent in mh.get('entities') or ()
                          if ent['label'] == lbl
                          for ch in ent['checks'] if ch['verdict'] == 'UNHEALTHY'), ''))
                + '</p></div>' for lbl in bad)
        if blind:
            body += ''.join(
                f'<div class="attn"><h4>{e(lbl.split(".")[-1])} — свежо, но доверять '
                f'нельзя</h4><p class="note">'
                + e(next((ch['why'] for ent in mh.get('entities') or ()
                          if ent['label'] == lbl
                          for ch in ent['checks'] if ch['verdict'] == 'BLIND'), ''))
                + '</p></div>' for lbl in blind)
        rows = ''.join(
            f'<div class="cmp"><span>{e(ent["label"])}</span>'
            f'<span>{e(ent.get("tier"))}</span>'
            f'<span>{e(HEALTH_WORD.get(ent["verdict"], ent["verdict"]))}</span></div>'
            for ent in mh.get('entities') or ())
        body += _details(f'контракты здоровья: объявлено {declared}',
                         '<div class="cmp"><span class="hd">служба</span>'
                         '<span class="hd">важность</span><span class="hd">вердикт</span>'
                         f'</div>{rows}', note=mh.get('coverage_note'))
    else:
        body += (f'<p class="note"><b>Здоровье не измерено ни у одной службы.</b> '
                 f'{e(h.get("health_contract_note") or "")}</p>')
    body += _details('по роду (и на каком основании род присвоен)',
                     _counters(h.get('by_kind') or {}, limit=8)
                     + f'<p class="note">{e(h.get("kind_note") or "")}</p>')
    body += _details('по форме исполнения', _counters(h.get('by_schedule_class') or {}))
    ents = h.get('entities') or []
    rows = ''.join(
        f'<div class="cmp"><span>{e(x.get("label"))}</span>'
        f'<span>{e(x.get("kind"))}</span>'
        f'<span>{e(RUNNING_WORD.get((x.get("stages") or {}).get("RUNNING"), "не измерено"))}</span></div>'
        for x in ents[:120])
    body += _details(f'все службы: {len(ents)}',
                     '<div class="cmp"><span class="hd">служба</span><span class="hd">род</span>'
                     f'<span class="hd">работает ли</span></div>{rows}')
    out.append(_card('Что сейчас работает', body))

    # 4. МОСТ — из улик, без вбитых чисел
    b = bridge or {}
    if b.get('state') == 'READ':
        body = _stats([
            (b.get('task_count'), 'задач', ''),
            (b.get('commits_verified_count'), 'доставок подтверждено в git', ''),
            (b.get('gates_approved'), 'гейтов одобрено владельцем', ''),
            (b.get('artifacts_table_rows'), 'строк в таблице улик', ''),
        ])
        body += (f'<p class="note">Дальше всего доказывает БАЗА: '
                 f'<b>{e(b.get("furthest_proven_by_database"))}</b>; каталог прогона: '
                 f'<b>{e(b.get("furthest_proven_by_disk_evidence"))}</b>. '
                 f'{e(b.get("carrier_note") or "")}</p>')
        failing = b.get('delivered_with_failing_tests') or []
        if failing:
            body += (f'<p class="note"><b>Доставлено с красными тестами: '
                     f'{len(failing)}.</b> Манифест применения сам записал '
                     f'tests_passed=false, и коммит всё равно был применён.</p>')
        nf = b.get('commits_not_found') or []
        if nf:
            body += (f'<p class="note">Коммитов заявлено в манифестах, но НЕ найдено в '
                     f'канонических репозиториях: {len(nf)}. Это не «пропали» — это '
                     f'значит, что они легли в рабочие клоны, а не в канон.</p>')
        body += _details('население стадий',
                         _counters(b.get('stage_population') or {}, limit=12),
                         note='у стадий РАЗНЫЕ носители улик, и ноль у стадии без '
                              'носителя означает «не измерено», а не «не было»')
        body += _details(f'разрывы контракта улик: {b.get("contract_gap_count")}',
                         ''.join(f'<div class="attn"><h4>{e(g.get("anomaly"))}</h4>'
                                 f'<p class="note">{e(g.get("classification"))} — '
                                 f'{e(g.get("evidence_note") or g.get("evidence") or "")}</p></div>'
                                 for g in b.get('contract_gaps') or ()))
    else:
        body = (f'<p class="muted">{e(b.get("reason") or "мост не измерен")}</p>')
    out.append(_card('Мост', body))

    # 5. ИССЛЕДОВАНИЯ — два РАЗНЫХ контура
    if rnd and rnd.get('question_count'):
        body = _stats([
            (rnd.get('question_count'), 'вопросов выведено из улик', ''),
            (rnd.get('loop_stage_reached') or 'не измерено', 'стадия петли', ''),
        ])
        body += _counters(rnd.get('by_trigger') or {}, limit=8)
        body += (f'<p class="note">{e(rnd.get("running_note") or "")}</p>'
                 f'<p class="note">{e(rnd.get("production_note") or "")}</p>')
        rows = ''
        for q in rnd.get('questions') or ():
            rows += (f'<div class="stagerow"><span class="n">?</span>'
                     f'<span>{e(q.get("question"))}</span><span></span>'
                     f'<p class="ev">улика: {e(str(q.get("evidence"))[:150])}</p></div>')
        body += _details(f'задел вопросов: {rnd.get("question_count")}', rows,
                         note=rnd.get('derivation_note'))
        out.append(_card('Исследования самой системы', body))

    # 6. Архитектор и CIO.
    #
    # Здесь стоял ДЕФЕКТ того самого рода, против которого написан весь выпуск: экран
    # УТВЕРЖДАЛ «CIO в рантайме: DOCUMENTED_ONLY», взяв это из литерала по умолчанию —
    # ни один вызывающий такого состояния не измерял. Владелец поправил: CIO здесь
    # означает Chief Investment Officer, и он построен. Замер подтвердил: есть ярлык
    # расписания, есть модуль, есть больше десяти артефактов.
    #
    # Поэтому литерал убран. Неизмеренное состояние называется неизмеренным и несёт
    # причину; вердикт о жизненном цикле подаётся только замером.
    measured = (roles or {}).get('roles') or {}
    arch = _lifecycle_claim((measured.get('ARCHITECT') or {}).get('state')
                            or (layer or {}).get('architect_state'), 'Архитектор')
    cio_row = measured.get('CIO') or {}
    cio = _lifecycle_claim(cio_row.get('state') or (layer or {}).get('cio_state'), 'CIO')
    cio_name = cio_row.get('display_name') or 'CIO'
    body = _kv([('Архитектор в рантайме', arch['label']),
                (f'{cio_name} в рантайме', cio['label']),
                ('Ёмкость исполнителя', 'НЕ ИЗМЕРЕНО'),
                ('Реестр выпусков', 'НЕ СУЩЕСТВУЕТ')])
    for claim in (arch, cio):
        if claim['note']:
            body += f'<p class="note">{e(claim["note"])}</p>'
    for key, row in sorted(measured.items()):
        if not row.get('why'):
            continue
        ev = row.get('evidence') or {}
        body += _details(
            f'откуда состояние «{e(row.get("display_name") or key)}»',
            _kv([('вердикт', row.get('state')), ('почему', row.get('why')),
                 ('модуль', ev.get('module')),
                 ('расписание, с', (ev.get('schedule') or {}).get('start_interval')),
                 ('выход', ev.get('output')),
                 ('возраст выхода, ч', ev.get('output_age_hours')),
                 ('читателей', ev.get('consumer_count'))])
            + (('<div class="cmp">' + ''.join(
                f'<span>{e(c["file"])}:{e(c["line"])}</span><span></span>'
                f'<span>{e(c["code"][:64])}</span>' for c in (ev.get('consumers') or [])[:6])
               + '</div>') if ev.get('consumers') else ''),
            note=row.get('derivation_note'))
    body += ('<p class="note">DOCUMENTED_ONLY означает: слой описан документами, '
             'работающего компонента с артефактом и расписанием нет. Совпадение по имени '
             'ярлыка уликой не является — но и ОТСУТСТВИЕ замера не является '
             'основанием объявить слой ненаписанным.</p>')
    cl = classification or {}
    if cl.get('state') == 'MEASURED':
        body += _stats([
            (f"{cl.get('routed_pct')} %", 'карточек отнесено правилом', ''),
            (cl.get('suggested_only'), 'только подсказка', ''),
            (cl.get('prose_scope_declared'), 'со своим скоупом в прозе', ''),
        ])
        body += (f'<p class="note">{e(cl.get("note") or "")}</p>'
                 f'<p class="note">{e(cl.get("prose_note") or "")}</p>')
    out.append(_card('Роли, Архитектор и ёмкость', body))

    du = durability or {}
    if du.get('state') == 'READ':
        led, ring, bak = du.get('ledger') or {}, du.get('ring_buffer') or {}, \
            du.get('backup_claims') or {}
        body = _stats([
            (led.get('ledger', {}).get('day_count'), 'закрытых дней под учётом', ''),
            (led.get('rewritten_count'), 'прошлых дней переписано', ''),
            (ring.get('days_until_truncation'), 'дней до обрезания ряда', ''),
            (bak.get('false_ok_count'), 'дней «ok» без архива', ''),
        ])
        if led.get('verdict') == 'PAST_REWRITTEN':
            body += ('<div class="attn decide"><h4>Закрытые дни изменились после '
                     'записи</h4><p class="note">'
                     + e('; '.join(f"{w['date']}: {w['close_equity_before']} → "
                                   f"{w['close_equity_now']}"
                                   for w in led.get('rewritten') or ()))
                     + '</p></div>')
        if ring.get('warning'):
            body += (f'<div class="attn"><h4>Ряд скоро начнёт терять историю сам</h4>'
                     f'<p class="note">ёмкость {e(ring.get("cap"))} точек, осталось '
                     f'{e(ring.get("days_until_truncation"))} дн. · первая точка под '
                     f'угрозой {e(ring.get("first_point_at_risk"))}</p></div>')
        if bak.get('false_ok_count'):
            body += (f'<div class="attn"><h4>Сторож отвечает «ok» об отсутствующем '
                     f'архиве</h4><p class="note">дни: '
                     f'{e(", ".join(bak.get("days_claimed_ok_without_archive") or ()))} · '
                     f'окно хранения с {e(bak.get("retention_window_start"))}</p></div>')
        body += f'<p class="note">{e(du.get("summary_note") or "")}</p>'
        out.append(_card('Долговечность истории', body))
    return ''.join(out)


# ── BUILD ─────────────────────────────────────────────────────────────────────

STATUS_WORD = {'LIVE': 'работает', 'PARTIAL': 'частично', 'DOCUMENTED_ONLY': 'только на бумаге',
               'NOT_FOUND': 'не найдено', 'UNKNOWN': 'не измерено'}
HANDOFF_WORD = {'YES': 'передаёт дальше', 'NO': 'дальше не передаёт',
                'UNKNOWN': 'передача не измерена'}


def render_build(*, pipeline, bridge, work=None):
    out = []
    p = pipeline or {}
    brk = p.get('autonomy_breaks_at') or {}
    if brk:
        body = (f'<div class="attn decide"><h4>Автономия останавливается на переходе: '
                f'{e(brk.get("title"))} → '
                f'{e(dict((s["stage"], s["title"]) for s in p.get("stages") or ()).get(brk.get("hand_off_to"), brk.get("hand_off_to")))}'
                f'</h4><p class="note">мешает стадия «{e(brk.get("blocked_by_stage"))}» '
                f'({e(STATUS_WORD.get(brk.get("blocked_by_status"), brk.get("blocked_by_status")))}): '
                f'{e(brk.get("reason"))}</p></div>')
    else:
        body = '<p class="muted">разрыв автономии не измерен</p>'
    body += _stats([(v, STATUS_WORD.get(k, k.lower()), '')
                    for k, v in (p.get('counts') or {}).items() if v])
    body += (f'<p class="note">«Работает» требует улики не старше '
             f'{e(p.get("live_window_days"))} дн. Механизм, доказанный однажды и '
             f'молчащий сейчас, — это «частично», а не «работает».</p>')
    out.append(_card('Где останавливается автономия', body, tone='warn' if brk else ''))

    rows = ''
    for i, s in enumerate(p.get('stages') or (), 1):
        rows += (f'<div class="stagerow"><span class="n">{i}</span>'
                 f'<span>{e(s.get("title"))}</span>'
                 f'<span><span class="tag {"obs" if s.get("status") == "LIVE" else "unver"}">'
                 f'{e(STATUS_WORD.get(s.get("status"), s.get("status")))}</span></span>'
                 f'<p class="ev">улик {e(_num(s.get("evidence_count")))} · '
                 f'{e(HANDOFF_WORD.get(s.get("can_hand_off"), ""))} · '
                 f'носитель: {e(s.get("evidence_carrier") or "носителя нет")}</p></div>')
    body = rows + f'<p class="note">{e(p.get("derivation_note") or "")}</p>'
    body += _details('правило приёмки каждой стадии',
                     ''.join(f'<div class="cmp"><span>{e(s.get("title"))}</span>'
                             f'<span colspan="2">{e(s.get("acceptance_rule"))}</span>'
                             f'<span></span></div>' for s in p.get('stages') or ()))
    out.append(_card('Конвейер', body))

    b = bridge or {}
    if b.get('state') == 'READ':
        rows = ''.join(
            f'<div class="cmp"><span>{e(str(t.get("task_id"))[:44])}</span>'
            f'<span>{e(t.get("status"))}</span>'
            f'<span>{e(t.get("furthest_proven_stage") or "не доказано")}</span></div>'
            for t in b.get('tasks') or ())
        body = ('<div class="cmp"><span class="hd">задача</span><span class="hd">статус</span>'
                f'<span class="hd">дальше всего доказано</span></div>{rows}')
        ver = b.get('commits_verified') or []
        if ver:
            body += _details(
                f'подтверждённые доставки: {len(ver)}',
                ''.join(f'<div class="cmp"><span>{e(c.get("subject"))}</span>'
                        f'<span>{e(c.get("repository"))}</span>'
                        f'<span>{e(str(c.get("committed_at"))[:10])}</span></div>'
                        for c in ver),
                note='подтверждение — чтение git, а не запись в базе')
        out.append(_card('Задачи моста', body))

    body = _counters((work or {}).get('counts') or {}, limit=10)
    body += ('<p class="note">«+ Создать» — ПОКА НЕ ВКЛЮЧЕНО. Кокпит только читает: '
             'ни одного действия отсюда выполнить нельзя.</p>')
    out.append(_card('Работа', body))
    return ''.join(out)


# ── Страница ──────────────────────────────────────────────────────────────────

def _human_stamp(value):
    """Отметка для человека. Сырой ISO с микросекундами — формат для машины."""
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return str(value)
    return dt.strftime('%d.%m.%Y %H:%M UTC')


def shell_html(projection, *, generated_at=None, freshness=None):
    """Одна страница, три вида. Ни сети, ни кнопок, ни действий."""
    v13 = projection.get('v13') or {}
    layers = projection.get('layers') or {}
    stamp = _human_stamp(generated_at or projection.get('generated_at') or '')
    bodies = {
        # Свежесть сборки — служебная карточка, и она уходит ВНИЗ. Первый визуальный
        # проход показал её первой на экране: владелец открывал кокпит и видел
        # метаданные сборки прежде своих денег.
        'capital': (render_capital(v13.get('capital') or {},
                                   layer=layers.get('CAPITAL') or {})
                    + WS.render_freshness(freshness)),
        'studio': render_studio(health=v13.get('service_health'),
                                decisions=v13.get('owner_decisions'),
                                bridge=v13.get('bridge'),
                                rnd=v13.get('system_rnd') or v13.get('rnd'),
                                layer=layers.get('STUDIO') or {},
                                measured_health=v13.get('measured_health'),
                                durability=v13.get('history_durability'),
                                classification=v13.get('classification'),
                                roles=v13.get('roles')),
        'build': render_build(pipeline=v13.get('pipeline'), bridge=v13.get('bridge'),
                              work=(layers.get('STUDIO') or {}).get('work')),
    }
    views = ''.join(
        f'<div class="view" id="view-{slug}">'
        f'<h2 class="viewhead">{icon} {e(title)}</h2>'
        f'<p class="viewq">{e(question)}</p>{bodies[slug]}</div>'
        for slug, title, icon, question in WS.LAYERS)
    tabs = ''.join(
        f'<a id="tab-{slug}" href="#{slug}"><span class="ico">{icon}</span>{e(title)}</a>'
        for slug, title, icon, _q in WS.LAYERS)
    digest = projection.get('semantic_digest') or ''
    fdigest = v13.get('fact_digest') or ''
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
        f'<link rel="manifest" href="./{WS.MANIFEST_FILE}">'
        f'<link rel="apple-touch-icon" href="./{WS.ICON_FILE}">'
        f'<link rel="icon" type="image/svg+xml" href="./{WS.ICON_FILE}">'
        '<title>CAPITAL · Director OS</title>'
        f'<style>{WS.CSS}{CSS_V13}</style></head><body>'
        '<header><h1>🏛 Director OS</h1>'
        f'<p class="sub">закрытый кокпит владельца · ТОЛЬКО ЧТЕНИЕ · собрано {e(stamp)}</p>'
        '</header>'
        f'<nav aria-label="Слои Director OS">{tabs}</nav>'
        f'<main>{views}</main>'
        '<footer>Производная проекция, не источник правды. '
        f'Отпечаток проекции {e(digest)} · отпечаток смысла фактов {e(fdigest)}. '
        f'Как есть {e(stats.get("SAFE_FOR_PRIVATE_WEB"))} · '
        f'отредактировано {e(stats.get("REDACTED"))} · '
        f'только локально {e(stats.get("LOCAL_ONLY"))} · '
        f'не опубликовано как UNKNOWN {e(stats.get("UNKNOWN_BLOCKED"))}.'
        '</footer>'
        f'<script>{WS.JS}</script></body></html>')


#: Фразы, которых на странице быть НЕ ДОЛЖНО. Каждая — исправленный дефект v1.2,
#: и проверка существует, чтобы он не вернулся молча. Литералы собираются из кусков:
#: иначе сам список сделал бы страницу-носителя проверки непроходимой.
FORBIDDEN_PHRASES = (
    ('эквити, ' + 'USDC', 'валюта не приписывается ряду, который её не объявляет'),
)


def validate_shell(page, where):
    """Контракт оболочки v1.3. Отказывает, а не чинит."""
    WS.validate_shell(page, where)

    def need(cond, message):
        if not cond:
            raise WS.ShellError(f'{where}: {message}')

    for phrase, why in FORBIDDEN_PHRASES:
        need(phrase not in page, f'запрещённая формулировка «{phrase}»: {why}')
    need('МАКСИМАЛЬНАЯ просадка' in page and 'просадка СЕЙЧАС' in page,
         'две просадки обязаны быть разведены словами: одно слово на две величины — '
         'это дефект v1.2, ради которого выпуск и делался')
    need('Что ждёт моего решения' in page,
         'очередь решений владельца обязана быть на экране')
    need('Автономия останавливается на переходе' in page
         or 'разрыв автономии не измерен' in page,
         'разрыв автономии обязан быть назван или честно объявлен неизмеренным')
    need('здоровье' in page.lower() and 'НЕ измерено' in page,
         'неизмеренное здоровье обязано быть названо неизмеренным')
    need('REAL CAPITAL: NOT PROVEN' in page,
         'политика REAL обязана оставаться на экране')
    return True
