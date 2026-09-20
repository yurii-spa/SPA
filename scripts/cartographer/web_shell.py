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


# ── CAPITAL ───────────────────────────────────────────────────────────────────
def render_capital(layer):
    if layer.get('state') == 'NOT_READ':
        return _card('Капитал', f'<p class="muted">{e(layer.get("note"))}</p>', tone='unknown')

    out = []
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
        f'<span class="v">{e(_num(by_mode.get(m)))}</span></div>'
        for m in ('REAL', 'PAPER', 'SHADOW', 'FORECAST', 'RND', 'UNKNOWN')
        if m in by_mode)
    out.append(_card('Капитал по режимам', f'<div class="modes">{rows}</div>',
                     note='режимы НИКОГДА не складываются в одно число'))

    metrics = layer.get('capital_metrics') or []
    if metrics:
        cells = ''.join(
            f'<tr><td>{e(m.get("metric_type"))}</td><td>{e(m.get("mode"))}</td>'
            f'<td class="num">{e(_num(m.get("value")))}</td>'
            f'<td>{e(m.get("currency") or "не объявлена")}</td></tr>'
            for m in metrics)
        out.append(_card('Метрики капитала',
                         '<table><thead><tr><th>величина</th><th>режим</th>'
                         f'<th class="num">значение</th><th>валюта</th></tr></thead>'
                         f'<tbody>{cells}</tbody></table>',
                         note='«капитал» — не одно слово: настроено, эквити, позиции, кэш, '
                              'доход и PnL это РАЗНЫЕ величины'))

    ks = layer.get('kill_switch') or {}
    gl = layer.get('golive') or {}
    out.append(_card('Стоп-кран и готовность', _kv([
        ('стоп-кран сработал', ks.get('triggered')),
        ('основание', ks.get('reason')),
        ('гейты go-live', f"{_num(gl.get('passed'))} из {_num(gl.get('total'))}"),
        ('готовность объявлена', gl.get('ready')),
    ]), note='только чтение: ни стоп-кран, ни капитал этой оболочкой не трогаются'))

    rnd = layer.get('rnd_stage_counts') or {}
    counts = layer.get('counts') or {}
    out.append(_card('Стратегии и R&D', _counter_row(counts.get('by_mode') or {})
                     + _counter_row(rnd)
                     + _kv([('объектов', counts.get('objects')),
                            ('доказанно уникальных id', counts.get('proven_unique_strategy_ids')),
                            ('противоречивых фактов', counts.get('conflicting_facts'))]),
                     note='Director OS НЕ Investment Engine: стратегии здесь только читаются'))

    # Политика реальных денег обязана быть ВИДНА, а не только лежать в проекции:
    # правило, о котором владелец не прочитал, он не сможет и подтвердить.
    policy = layer.get('real_web_policy') or {}
    if policy:
        order = ('REAL_CAPITAL_SUMMARY', 'REAL_POSITION_DETAIL',
                 'WALLET_ACCOUNT_IDENTIFIER', 'RAW_INVESTMENT_EVIDENCE')
        rows = ''.join(
            f'<tr><td>{e(REAL_CLASS_LABELS.get(k, k))}</td>'
            f'<td class="{"never" if policy.get(k) == "NEVER" else "blocked"}">'
            f'{e(policy.get(k))}</td></tr>'
            for k in order if k in policy)
        out.append(_card('Реальные деньги: что будет показано, когда появятся',
                         '<table><thead><tr><th>класс данных</th>'
                         f'<th>в закрытом вебе</th></tr></thead><tbody>{rows}</tbody></table>',
                         note=e(layer.get('real_policy_note') or ''),
                         tone='warn'))

    limits = layer.get('limits') or []
    if limits:
        items = ''.join(f'<li>{e(x)}</li>' for x in limits[:TOP_N])
        more = (f'<p class="note">показано {min(len(limits), TOP_N)} из {len(limits)}</p>'
                if len(limits) > TOP_N else '')
        out.append(_card('Границы этого слоя', f'<ul>{items}</ul>{more}'))
    return ''.join(out)


# ── STUDIO ────────────────────────────────────────────────────────────────────
def render_studio(layer, architect=None, cio=None, bridge=None):
    out = []
    state = layer.get('system_state')
    tone = {'НОРМАЛЬНО': 'ok', 'ТРЕБУЕТ ВНИМАНИЯ': 'warn'}.get(state, 'unknown')
    out.append(_card(f'Состояние системы: {state or "НЕ ИЗМЕРЕНО"}',
                     f'<p>{e(layer.get("system_state_reason"))}</p>',
                     note='общего балла здоровья нет намеренно: разные риски в один балл '
                          'не сводятся',
                     tone=tone))

    blocks = layer.get('blocks') or {}
    if blocks:
        rows = ''.join(
            f'<tr><td>{e(BLOCK_LABELS.get(name, name))}</td>'
            f'<td class="num">{e(_num(b.get("shown")))}</td>'
            f'<td class="num">{e(_num(b.get("count")))}</td></tr>'
            for name, b in sorted(blocks.items(),
                                  key=lambda kv: -(kv[1].get('count') or 0)))
        out.append(_card('Что требует внимания',
                         '<table><thead><tr><th>блок</th><th class="num">показано</th>'
                         f'<th class="num">всего</th></tr></thead><tbody>{rows}</tbody></table>',
                         note=f'на экране не больше {TOP_N} строк в блоке — так задумано; '
                              'полное число в правой колонке'))

    rel = layer.get('reliability') or {}
    rc = rel.get('counts') or {}
    out.append(_card('Надёжность',
                     _counter_row(rc.get('by_classification') or {})
                     + _counter_row(rc.get('by_severity') or {})
                     + _kv([('подтверждено сейчас', rc.get('active_confirmed')),
                            ('требует перепроверки', rc.get('active_unverified')),
                            ('CRITICAL подтверждённых', rc.get('critical_confirmed_now'))]),
                     note='«требует перепроверки» — это НЕ расхождение и не инцидент'))

    work = layer.get('work') or {}
    wc = work.get('counts') or {}
    ident = work.get('identity') or {}
    out.append(_card('Работа',
                     _counter_row(wc.get('by_owner_view_state') or {})
                     + _kv([('ждёт владельца', wc.get('waiting_owner')),
                            ('заблокировано', wc.get('blocked')),
                            ('в работе', wc.get('in_progress')),
                            ('уникальных работ доказано',
                             ident.get('proven_unique_work_count'))]),
                     note='один заголовок в двух реестрах — это НЕ доказательство, '
                          'что работа одна'))

    gov = layer.get('governance') or {}
    gc = gov.get('counts') or {}
    out.append(_card('Управление и восстановление',
                     _counter_row(gc.get('by_recovery_status') or gc.get('by_recovery_state') or {})
                     + _kv([('гейтов владельца', gc.get('owner_gated')),
                            ('автономных правил', gc.get('autonomous_rules')),
                            ('коллизий номеров ADR', gc.get('adr_number_collisions')),
                            ('резервов наблюдено', gc.get('backups_observed')),
                            ('восстановление испытано', gc.get('recovery_tested'))]),
                     note='резерв наблюдён ≠ восстановление испытано; '
                          'runbook описан ≠ испытан'))

    # Архитектор и CIO: показывать ровно то, что измерено, и ни словом больше.
    for title, rec in (('Архитектор', architect), ('CIO', cio)):
        rec = rec or {'state': 'UNKNOWN', 'note': 'состояние не подавали'}
        st = rec.get('state', 'UNKNOWN')
        out.append(_card(f'{title}: {st}', f'<p>{e(rec.get("note"))}</p>',
                         note='DOCUMENTED_ONLY означает: документ есть, работающей '
                              'реализации не найдено. Изображать её работающей нельзя',
                         tone='unknown' if st != 'LIVE' else 'ok'))

    if bridge:
        d = bridge.get('daemons') or {}
        out.append(_card(f'Bridge: {bridge.get("state", "UNKNOWN")}',
                         _kv([('репозиторий', bridge.get('repo'))]
                             + sorted(d.items())),
                         note=e(bridge.get('note') or ''),
                         tone='ok' if bridge.get('state') == 'LIVE' else 'unknown'))
    return ''.join(out)


# ── BUILD ─────────────────────────────────────────────────────────────────────
def render_build(layer):
    out = []
    # «+ Создать» — намеренно НЕ <button>: нечего нажать, значит нечего исполнить.
    out.append(
        '<section class="card disabled" aria-disabled="true">'
        '<div class="create"><span class="plus">+</span>'
        '<span class="createlabel">Создать</span>'
        '<span class="badge">ПОКА НЕ ВКЛЮЧЕНО</span></div>'
        '<p class="note">так это будет выглядеть. В Epic 1 действий нет ни одного: '
        'ни задачи, ни исполнения, ни одобрения отсюда не запускается.</p>'
        '</section>')

    intake = layer.get('owner_intake') or []
    if intake:
        rows = ''.join(
            f'<tr class="{"yes" if i.get("available") else "no"}">'
            f'<td>{e(i.get("intake_kind"))}</td>'
            f'<td>{"есть" if i.get("available") else "НЕ НАЙДЕНО"}</td>'
            f'<td>{e(i.get("note"))}</td></tr>' for i in intake)
        out.append(_card('Чем владелец уже может подать задачу',
                         '<table><thead><tr><th>вид</th><th>состояние</th>'
                         f'<th>как</th></tr></thead><tbody>{rows}</tbody></table>',
                         note='это замер уже существующих каналов, а не план'))

    bridge = layer.get('bridge') or {}
    if bridge:
        db = bridge.get('db') or {}
        code = bridge.get('code') or {}
        out.append(_card(f'Bridge: {bridge.get("state", "NOT_MEASURED")}',
                         _kv(sorted(db.items()) + sorted(code.items())),
                         note=e(bridge.get('note') or '')))

    audit = layer.get('action_audit') or {}
    ac = audit.get('counts') or {}
    out.append(_card('Почему кнопок нет',
                     _kv([('кандидатов', ac.get('candidates')),
                          ('готовы для UI', ac.get('ready_for_ui')),
                          ('не готовы', ac.get('not_ready')),
                          ('запрещено навсегда', ac.get('red_zone'))]),
                     note='ноль готовых действий — это ИЗМЕРЕНО, а не решено: пяти '
                          'кандидатам не хватает записи в аудит, идемпотентности и отката',
                     tone='warn'))

    actions = audit.get('actions') or []
    if actions:
        rows = ''.join(
            f'<tr><td>{e(a.get("action"))}</td><td>{e(a.get("verdict"))}</td>'
            f'<td>{e(", ".join(a.get("missing_properties") or []) or "—")}</td></tr>'
            for a in actions[:TOP_N])
        more = (f'<p class="note">показано {min(len(actions), TOP_N)} из {len(actions)}</p>'
                if len(actions) > TOP_N else '')
        out.append(_card('Разобранные действия',
                         '<table><thead><tr><th>действие</th><th>вердикт</th>'
                         f'<th>чего не хватает</th></tr></thead><tbody>{rows}</tbody></table>'
                         + more))

    red = audit.get('red_zone') or []
    if red:
        chips = ''.join(f'<span class="chip red">{e(x)}</span>' for x in red)
        out.append(_card('Красная зона — не обсуждается',
                         f'<div class="chips">{chips}</div>',
                         note='эти глаголы не попадают в UI ни при каких свойствах'))
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
  table{display:table}
  th,td{white-space:normal}
}
@media (prefers-color-scheme:light){
  :root{--bg:#f6f7f9;--card:#fff;--line:#e2e5ea;--fg:#14161a;--mut:#5b6472;--unk:#8b94a3}
  header{background:rgba(246,247,249,.94)}
  nav{background:rgba(255,255,255,.97)}
  .mode,.chip{background:#f1f3f6}
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
        'build': render_build(layers.get('BUILD') or {}),
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
