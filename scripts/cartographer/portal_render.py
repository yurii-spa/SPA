#!/usr/bin/env python3
"""Layer C + D: one static page for the studio portal, built offline.

Input: a `portal_snapshot.json` and the accepted Owner Briefing. Nothing is read from
production here, nothing from the network, and no fact is added — a line on the page must
exist in the snapshot.

The page is plain by construction: one file, inline styles, inline data, no CDN, no
external font, no analytics, no `fetch`. The only scripting is search, filtering and
sorting over rows already present in the DOM. There is no control that starts, stops,
assigns, closes, approves, restarts, deploys or fixes anything — this phase is read-only,
and an inert button pretending otherwise would be worse than none.

Offline by construction: no ``subprocess``, no ``socket``, no ``urllib``.
"""
import html as _html
import json

RENDER_CONTRACT = 'cartographer.portal_page/0.1'

#: Verbs a control must never carry in this phase. Checked by a test over the page.
FORBIDDEN_ACTIONS = ('запустить', 'остановить', 'назначить', 'закрыть', 'approve',
                     'reject', 'restart', 'deploy', 'выполнить', 'исправить', 'перезапустить')

STAGE_WORDS = {True: 'да', False: 'нет', None: 'UNKNOWN'}


def _e(value):
    if value is None:
        return '—'
    if isinstance(value, bool):
        return 'да' if value else 'нет'
    return _html.escape(str(value), quote=True)


def _cut(value, limit=160):
    text = '' if value is None else str(value)
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _group_badge(group):
    cls = {'закрыто': 'b-ok', 'в работе': 'b-warn', 'не начато': 'b-unk'}.get(group, 'b-unk')
    return f'<span class="badge {cls}">{_e(group)}</span>'


_CSS = """
:root{--bg:#fbfbf9;--fg:#1d1d1b;--mut:#5d5d57;--line:#dedcd4;--card:#fff;
--warn:#8a5a00;--warnbg:#fdf4e3;--unk:#41506b;--unkbg:#eef1f6;--ok:#2f5d3a;--okbg:#eef5ef;
--acc:#2a4a7c}
@media (prefers-color-scheme:dark){:root{--bg:#16161a;--fg:#ececea;--mut:#a3a39c;
--line:#30302f;--card:#1e1e22;--warn:#e8b562;--warnbg:#2a2318;--unk:#a8bade;--unkbg:#1b2130;
--ok:#8bc79a;--okbg:#18231b;--acc:#9ab4dd}}
*{box-sizing:border-box}
body{margin:0;padding:0 0 48px;background:var(--bg);color:var(--fg);
font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
-webkit-text-size-adjust:100%}
.wrap{max-width:1000px;margin:0 auto;padding:16px}
nav{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);
padding:8px 16px;display:flex;gap:6px;flex-wrap:wrap}
nav a{color:var(--acc);text-decoration:none;border:1px solid var(--line);border-radius:999px;
padding:.2em .7em;font-size:.86rem;white-space:nowrap}
nav a:focus{outline:2px solid var(--acc);outline-offset:2px}
h1{font-size:1.4rem;margin:.3em 0 .1em}
h2{font-size:1.15rem;margin:1.5em 0 .4em;padding-top:.6em;border-top:1px solid var(--line)}
h3{font-size:1rem;margin:1em 0 .3em}
p,li{margin:.4em 0}
.sub{color:var(--mut);font-size:.9rem}
.note{color:var(--mut);font-size:.88rem}
.evi{color:var(--mut);font-size:.8rem;overflow-wrap:anywhere}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:10px 12px;margin:.55em 0}
.kv{display:grid;grid-template-columns:minmax(8rem,auto) 1fr;gap:.2em .7em;font-size:.92rem}
.kv dt{color:var(--mut)}
.kv dd{margin:0;overflow-wrap:anywhere}
.badge{display:inline-block;padding:.05em .5em;border-radius:6px;font-size:.78rem;
font-weight:600;border:1px solid currentColor;white-space:nowrap}
.b-ok{color:var(--ok);background:var(--okbg)}
.b-warn{color:var(--warn);background:var(--warnbg)}
.b-unk{color:var(--unk);background:var(--unkbg)}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85em;
overflow-wrap:anywhere;word-break:break-word}
table{border-collapse:collapse;width:100%;font-size:.88rem;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:.35em .5em;text-align:left;vertical-align:top}
th{background:var(--unkbg)}
details{margin:.35em 0}
summary{cursor:pointer;color:var(--mut);font-size:.9rem}
summary:focus{outline:2px solid var(--acc);outline-offset:2px}
.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:.6em 0}
.controls input,.controls select{font:inherit;font-size:.9rem;padding:.35em .5em;
border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
.controls input{flex:1 1 14rem;min-width:0}
.row{border-bottom:1px solid var(--line);padding:.5em 0}
.row[hidden]{display:none}
.rowhead{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.rowtitle{font-weight:600;overflow-wrap:anywhere}
.big{font-size:1.05rem;font-weight:600;overflow-wrap:anywhere}
/* Найдено настоящим viewport 390px: 40-символьный git-SHA в <strong> не переносился и
   давал 29px горизонтального вылета документа. Значения в карточках ломаются по любому
   месту — идентификатор длиннее строки не должен ломать страницу. */
.card strong,.card div{overflow-wrap:anywhere}
.empty{padding:1em;border:1px dashed var(--line);border-radius:10px;color:var(--mut)}
.count{color:var(--mut);font-size:.86rem}
@media (max-width:520px){.wrap{padding:12px 10px}h1{font-size:1.2rem}
.kv{grid-template-columns:1fr}.kv dt{margin-top:.35em}}
"""

_JS = """
function spaFilter(scope){
  var root=document.getElementById(scope);
  if(!root) return;
  var q=(root.querySelector('[data-role=search]').value||'').toLowerCase();
  var sel=root.querySelectorAll('[data-role=facet]');
  var shown=0, rows=root.querySelectorAll('.row');
  for(var i=0;i<rows.length;i++){
    var r=rows[i], ok=true;
    if(q && r.getAttribute('data-hay').indexOf(q)===-1) ok=false;
    for(var j=0;j<sel.length && ok;j++){
      var f=sel[j], want=f.value;
      if(want && r.getAttribute('data-'+f.getAttribute('data-facet'))!==want) ok=false;
    }
    r.hidden=!ok; if(ok) shown++;
  }
  var c=root.querySelector('[data-role=count]');
  if(c) c.textContent='показано '+shown+' из '+rows.length;
}
function spaSort(scope){
  var root=document.getElementById(scope);
  var key=root.querySelector('[data-role=sort]').value;
  var list=root.querySelector('[data-role=list]');
  var rows=Array.prototype.slice.call(list.querySelectorAll('.row'));
  rows.sort(function(a,b){
    var x=a.getAttribute('data-'+key)||'', y=b.getAttribute('data-'+key)||'';
    if(x===y) return (a.getAttribute('data-id')||'').localeCompare(b.getAttribute('data-id')||'');
    var desc = (key==='updated'||key==='rlast'||key==='rcount');
    return desc ? y.localeCompare(x) : x.localeCompare(y);
  });
  for(var i=0;i<rows.length;i++) list.appendChild(rows[i]);
}
"""


def _controls(scope, facets, sorts):
    parts = [f'<div class="controls" role="search">',
             f'<label class="note" for="{scope}-q">Поиск</label>',
             f'<input id="{scope}-q" type="search" data-role="search" '
             f'placeholder="заголовок, id, статус…" oninput="spaFilter(\'{scope}\')">']
    for facet, label, options in facets:
        parts.append(f'<label class="note" for="{scope}-{facet}">{_e(label)}</label>'
                     f'<select id="{scope}-{facet}" data-role="facet" data-facet="{facet}" '
                     f'onchange="spaFilter(\'{scope}\')"><option value="">все</option>'
                     + ''.join(f'<option value="{_e(o)}">{_e(o)}</option>' for o in options)
                     + '</select>')
    if sorts:
        parts.append(f'<label class="note" for="{scope}-sort">Сортировка</label>'
                     f'<select id="{scope}-sort" data-role="sort" '
                     f'onchange="spaSort(\'{scope}\')">'
                     + ''.join(f'<option value="{_e(k)}">{_e(v)}</option>'
                               for k, v in sorts) + '</select>')
    parts.append(f'<span class="count" data-role="count"></span></div>')
    return ''.join(parts)


# ── screens ──────────────────────────────────────────────────────────────────

def _link(name, available, label=None):
    """A link only for a file that is really next to the page; otherwise plain text.

    Found by a test: the page linked `diff.json` and `changes.md` unconditionally, so a
    briefing set without them produced dead links. A dead link is worse than an honest
    "не приложен".
    """
    text = _e(label or name)
    if name in available:
        return f'<a href="{_e(name)}">{text}</a>'
    return f'<span class="note">{text} — не приложен к этому комплекту</span>'


def _overview(brief, available):
    if not brief:
        return ('<h2 id="overview">1. Обзор</h2><div class="empty">Сводка владельца '
                'недоступна: артефакт Owner Briefing не прочитан. Это НЕ значит, что '
                'изменений нет.</div>')
    f = brief['freshness_and_coverage']
    c = brief['counts']
    out = ['<h2 id="overview">1. Обзор студии</h2>',
           '<p class="note">Раздел целиком переиспользует принятую сводку Phase 1 — '
           'портал не считает изменения заново.</p>',
           '<div class="card"><dl class="kv">',
           f'<dt>Наблюдение снято</dt><dd class="mono">{_e(f["observed_at"])}</dd>',
           f'<dt>Возраст наблюдения</dt><dd>{_e(f["age_at_generation_human"])} '
           f'<span class="badge b-unk">порог: {_e(f["freshness_policy"])}</span></dd>',
           f'<dt>Подтверждённых изменений</dt><dd class="big">{c["confirmed_changes"]}</dd>',
           f'<dt>Требует внимания</dt><dd class="big">{c["attention_items"]}</dd>',
           f'<dt>Кандидатов решений</dt><dd class="big">{c["owner_candidates"]}</dd>',
           f'<dt>Неизвестного</dt><dd class="big">{c["unknown_findings"]} '
           f'в {c["unknown_groups"]} группах</dd>',
           f'<dt>Общая оценка здоровья</dt><dd>'
           f'<span class="badge b-unk">не выводится</span></dd></dl>',
           f'<p class="note">{_e(brief["overall_health_note"])}</p>',
           f'<p class="note">{_e(f["stale_summary_is_not_a_broken_system"])}</p>',
           '<p class="evi">полная сводка: '
           + _link('owner_briefing.md', available) + ' · '
           + _link('owner_briefing.json', available) + '</p></div>']
    changes = brief['material_changes']['confirmed']
    out.append('<h3>Существенные изменения</h3>')
    if not changes:
        out.append('<div class="empty">Подтверждённых существенных изменений нет. Это '
                   'корректный результат, а не пустая страница.</div>')
    for item in changes:
        out.append(f'<div class="card"><div class="big">{_e(item["headline"])}</div>'
                   f'<div class="mono">{_e(item["subject"])}'
                   + (f' · {_e(item["detail"])}' if item.get('detail') else '') + '</div>'
                   f'<div>{_e(_cut(item["old"], 120))} → '
                   f'<strong>{_e(_cut(item["new"], 120))}</strong></div>'
                   + (f'<p class="note">{_e(item["note"])}</p>' if item.get('note') else '')
                   + f'<div class="evi">evidence: <code>diff.json</code> → '
                     f'<code>changes[id={_e(item["id"])}]</code></div></div>')
    out.append('<h3>Требует внимания</h3>')
    for a in brief['attention']:
        examples = ''.join(f'<li><code>{_e(x["label"])}</code></li>' for x in a['examples'])
        out.append(f'<div class="card"><div class="big">{_e(a["headline"])} — '
                   f'{a["count"]}</div><p>{_e(a["practical_meaning"])}</p>'
                   f'<p class="note">критичность: '
                   f'<span class="badge b-unk">{_e(a["severity"])}</span></p>'
                   f'<details><summary>примеры и все {a["count"]} находок</summary>'
                   f'<ul>{examples}</ul><ul>'
                   + ''.join(f'<li><code>{_e(i)}</code></li>' for i in a['all_finding_ids'])
                   + '</ul></details></div>')
    out.append('<h3>Чего система не знает</h3><ul>')
    for u in brief['unknowns']:
        tag = ' <span class="badge b-unk">по построению</span>' if u['is_by_design'] else ''
        out.append(f'<li><code>{_e(u["rule_code"])}</code> — {u["count"]}{tag}: '
                   f'{_e(_cut(u["headline"], 140))}</li>')
    out.append('</ul>')
    return ''.join(out)


def _task_row(r):
    fields, acc = r['fields'], r['acceptance']
    updated = fields.get('updated') or fields.get('claimed_at') or fields.get('created') or ''
    if not acc['rule_applies_to_this_tracker']:
        acc_badge = '<span class="badge b-unk">правило приёмки не применяется</span>'
    elif r['status_group'] == 'закрыто':
        acc_badge = '<span class="badge b-warn">приёмка НЕ ПОДТВЕРЖДЕНА</span>'
    else:
        acc_badge = '<span class="badge b-unk">приёмка не применима</span>'
    hay = ' '.join(str(x).lower() for x in
                   (r['id'], r['title'] or '', r['status_raw'] or '', r['tracker'],
                    fields.get('domain') or '', fields.get('claimed_by') or '',
                    fields.get('priority') or ''))
    detail = ['<dl class="kv">',
              f'<dt>id</dt><dd class="mono">{_e(r["id"])}</dd>',
              f'<dt>тип записи</dt><dd>{_e(r["tracker"])} '
              f'<span class="note">(префикс файла: {_e(r["filename_prefix"])})</span></dd>',
              f'<dt>статус в источнике</dt><dd><code>{_e(r["status_raw"])}</code> → '
              f'{_group_badge(r["status_group"])}</dd>',
              f'<dt>основание группировки</dt><dd class="note">'
              f'{_e(r["status_group_basis"])}</dd>',
              f'<dt>приёмка</dt><dd>{acc_badge} <span class="note">'
              f'{_e(acc["verdict"])}</span></dd>',
              f'<dt>проба приёмки</dt><dd class="mono">{_e(acc["probe_declared"])}</dd>',
              f'<dt>результат пробы</dt><dd class="note">{_e(acc["result_source"])}</dd>',
              f'<dt>источник записи</dt><dd class="mono">{_e(r["source"]["path"])}</dd>',
              f'<dt>время файла</dt><dd class="mono">{_e(r["source"]["file_mtime"])}</dd>']
    for key in sorted(fields):
        if key in ('title',):
            continue
        value = fields[key]
        if isinstance(value, list):
            value = ', '.join(str(x) for x in value)
        detail.append(f'<dt>{_e(key)}</dt><dd class="mono">{_e(_cut(value, 400))}</dd>')
    if r.get('parse_error'):
        detail.append(f'<dt>разбор</dt><dd><span class="badge b-warn">'
                      f'{_e(r["parse_error"])}</span></dd>')
    if r.get('duplicate_of'):
        detail.append(f'<dt>дубль id</dt><dd><span class="badge b-warn">также в '
                      f'{_e(r["duplicate_of"])}</span></dd>')
    detail.append(f'<dt>тело записи</dt><dd class="note">{_e(r["body_note"])}</dd></dl>')
    return (f'<div class="row" data-id="{_e(r["id"])}" data-hay="{_e(hay)}" '
            f'data-tracker="{_e(r["tracker"])}" data-status="{_e(r["status_raw"])}" '
            f'data-group="{_e(r["status_group"])}" data-updated="{_e(updated)}" '
            f'data-title="{_e((r["title"] or r["id"]).lower())}">'
            f'<div class="rowhead">{_group_badge(r["status_group"])}'
            f'<span class="rowtitle">{_e(_cut(r["title"] or r["id"], 200))}</span>'
            f'<code class="note">{_e(r["status_raw"])}</code></div>'
            f'<details><summary>карточка и источник</summary>{"".join(detail)}</details>'
            f'</div>')


def _tasks(portal):
    tasks = portal['tasks']
    trackers = sorted({r['tracker'] for r in tasks})
    statuses = sorted({r['status_raw'] or 'NO_STATUS' for r in tasks})
    groups = sorted({r['status_group'] for r in tasks})
    out = ['<h2 id="tasks">2. Задачи</h2>',
           f'<p class="note">Записей: <strong>{len(tasks)}</strong> '
           f'({", ".join(f"{k}: {v}" for k, v in sorted(portal["counts"]["by_tracker"].items()) if k != "owner-decision")}). '
           'Статус показан в исходном виде; группировка рядом — по категории из '
           'определения трекера. Решения владельца — в отдельном разделе.</p>',
           '<div class="card"><strong>Записанный <code>done</code> — это не принятая '
           f'работа.</strong> <span class="note">Закрытых без подтверждённой приёмки: '
           f'{portal["counts"]["closed_inbox_without_confirmed_acceptance"]} '
           f'(правило относится только к очереди inbox). Артефакта с '
           'результатами проб приёмки в наблюдаемом дереве не найдено, поэтому приёмка '
           'у всех закрытых записей — НЕ ПОДТВЕРЖДЕНА.</span></div>',
           '<div id="tasks-scope">',
           _controls('tasks-scope',
                     [('tracker', 'Очередь', trackers), ('group', 'Группа', groups),
                      ('status', 'Статус', statuses)],
                     [('updated', 'по времени обновления'), ('title', 'по заголовку'),
                      ('status', 'по статусу')]),
           '<div data-role="list">']
    if not tasks:
        out.append('<div class="empty">Записи задач не извлечены. Проверьте раздел '
                   '«Источники»: недоступный источник — это не «задач нет».</div>')
    out.extend(_task_row(r) for r in tasks)
    out.append('</div></div>')
    return ''.join(out)


def _agents(portal):
    rows = portal['agents_and_roles']
    out = ['<h2 id="agents">3. Агенты и роли</h2>',
           f'<p class="note">Меток: <strong>{len(rows)}</strong>. Три источника '
           'показаны ОТДЕЛЬНО и не смешиваются: конфигурация роли (манифест), членство в '
           'реестре, наблюдение машины по стадиям. Связь с записью — только по '
           'проверяемому основанию.</p>',
           '<div class="card"><span class="note">Портал не утверждает «агент сейчас '
           'работает над задачей». <code>claimed_by</code> в карточках — строка '
           'исполнителя (цикл, PID, интерактивная сессия), а не метка launchd; упоминание '
           'метки в тексте записи назначением не является.</span></div>',
           '<div id="agents-scope">',
           _controls('agents-scope',
                     [('role', 'Роль', sorted({r['role_configuration']['role'] or 'UNKNOWN'
                                               for r in rows})),
                      ('obsstatus', 'Наблюдаемый статус',
                       sorted({r['observed']['status'] or 'UNKNOWN' for r in rows}))],
                     [('id', 'по метке'), ('role', 'по роли')]),
           '<div data-role="list">']
    for r in rows:
        rc, rg, ob = r['role_configuration'], r['registry_membership'], r['observed']
        stages = ''.join(
            f'<tr><td>{_e(k)}</td><td>{_e(STAGE_WORDS.get(v, v))}</td></tr>'
            for k, v in ob['stages'].items())
        links = ''.join(
            f'<li><code>{_e(l["record"])}</code> — {_e(l["relation"])}'
            f'<div class="evi">основание: {_e(l["basis"])} · назначения НЕ доказывает</div>'
            f'</li>' for l in r['task_links'])
        hay = ' '.join(str(x).lower() for x in
                       (r['id'], rc['role'] or '', rc['layer'] or '', ob['status'] or ''))
        out.append(
            f'<div class="row" data-id="{_e(r["id"])}" data-hay="{_e(hay)}" '
            f'data-role="{_e(rc["role"] or "UNKNOWN")}" '
            f'data-obsstatus="{_e(ob["status"] or "UNKNOWN")}">'
            f'<div class="rowhead"><span class="rowtitle mono">{_e(r["id"])}</span>'
            f'<span class="badge b-unk">{_e(rc["role"] or "роль UNKNOWN")}</span>'
            f'<span class="badge {"b-ok" if ob["status"] == "LIVE" else "b-warn" if ob["status"] in ("DEGRADED", "STALE") else "b-unk"}">'
            f'наблюдение: {_e(ob["status"] or "UNKNOWN")}</span></div>'
            f'<details><summary>три источника, стадии и связи</summary>'
            f'<h3>Конфигурация роли <span class="note">— что объявлено</span></h3>'
            f'<dl class="kv"><dt>в манифесте</dt><dd>{_e(rc["present_in_manifest"])}</dd>'
            f'<dt>слой / роль</dt><dd>{_e(rc["layer"])} / {_e(rc["role"])}</dd>'
            f'<dt>намерение</dt><dd>{_e(rc["intent"])}</dd>'
            f'<dt>расписание</dt><dd>{_e(rc["schedule"])}</dd>'
            f'<dt>produces / consumes</dt><dd>{rc["produces_count"]} / '
            f'{rc["consumes_count"]}</dd>'
            f'<dt>governed_by</dt><dd class="mono">{_e(", ".join(rc["governed_by"]) or None)}</dd>'
            f'<dt>доказывает</dt><dd class="note">{_e(rc["proves"])}</dd></dl>'
            f'<h3>Членство в реестре</h3>'
            f'<dl class="kv"><dt>в реестре</dt><dd>{_e(rg["present_in_registry"])}</dd>'
            f'<dt>роль / расписание</dt><dd>{_e(rg["role"])} / {_e(rg["schedule"])}</dd>'
            f'<dt>retired / reboot_safe</dt><dd>{_e(rg["retired"])} / '
            f'{_e(rg["reboot_safe"])}</dd>'
            f'<dt>доказывает</dt><dd class="note">{_e(rg["proves"])}</dd>'
            f'<dt>оговорка</dt><dd class="note">{_e(rg["note"])}</dd></dl>'
            f'<h3>Наблюдение машины <span class="note">— по стадиям, не одним словом</span></h3>'
            f'<table><thead><tr><th>стадия</th><th>значение</th></tr></thead>'
            f'<tbody>{stages}</tbody></table>'
            f'<dl class="kv"><dt>последний код выхода</dt><dd>{_e(ob["last_exit"])}</dd>'
            f'<dt>оговорка</dt><dd class="note">{_e(ob["last_exit_basis"])}</dd></dl>'
            f'<h3>Связи с записями</h3>'
            + (f'<ul>{links}</ul>' if links else
               '<p><span class="badge b-unk">UNLINKED</span> '
               '<span class="note">доказуемой связи с записями нет</span></p>')
            + (f'<p class="note">упоминаний метки в текстах записей: '
               f'{r["text_mentions"]} — назначением не является</p>'
               if r['text_mentions'] else '')
            + '</details></div>')
    out.append('</div></div>')
    return ''.join(out)


def _decisions(portal, brief):
    records = portal['owner_decision_records']
    candidates = (brief or {}).get('owner_decision_candidates') or []
    out = ['<h2 id="decisions">4. Решения владельца</h2>',
           '<div class="card"><strong>Два разных предмета, и они не смешиваются.</strong>'
           f'<div class="note">Записанных решений: {len(records)} — это канонические '
           'карточки, портал их не создаёт и не закрывает (инв. #14). Производных '
           f'кандидатов из Director OS: {len(candidates)} — это наблюдения, а не '
           'карточки.</div></div>',
           f'<h3>Записанные решения ({len(records)})</h3>',
           '<div id="decisions-scope">',
           _controls('decisions-scope',
                     [('status', 'Статус', sorted({r['status_raw'] or 'NO_STATUS'
                                                   for r in records})),
                      ('group', 'Группа', sorted({r['status_group'] for r in records}))],
                     [('updated', 'по времени'), ('title', 'по заголовку')]),
           '<div data-role="list">']
    if not records:
        out.append('<div class="empty">Записанных решений не извлечено. Это не значит, '
                   'что их нет — смотрите раздел «Источники».</div>')
    for r in records:
        f = r['fields']
        lifecycle = [(k, f[k]) for k in
                     ('owner_choice', 'owner_answered_at', 'owner_answer_via',
                      'owner_answered_by', 'owner_answer_kind', 'owner_choice_superseded',
                      'owner_decision', 'decision', 'answered', 'closed', 'closed_reason')
                     if k in f]
        trail = f.get('status_trail_last') or []
        hay = ' '.join(str(x).lower() for x in (r['id'], r['title'] or '',
                                                r['status_raw'] or ''))
        out.append(
            f'<div class="row" data-id="{_e(r["id"])}" data-hay="{_e(hay)}" '
            f'data-status="{_e(r["status_raw"])}" data-group="{_e(r["status_group"])}" '
            f'data-updated="{_e(f.get("owner_answered_at") or f.get("created") or "")}" '
            f'data-title="{_e((r["title"] or r["id"]).lower())}">'
            f'<div class="rowhead">{_group_badge(r["status_group"])}'
            f'<span class="rowtitle">{_e(_cut(r["title"] or r["id"], 200))}</span>'
            f'<code class="note">{_e(r["status_raw"])}</code></div>'
            f'<details><summary>жизненный цикл и источник</summary><dl class="kv">'
            f'<dt>id</dt><dd class="mono">{_e(r["id"])}</dd>'
            f'<dt>статус в источнике</dt><dd><code>{_e(r["status_raw"])}</code></dd>'
            f'<dt>основание группировки</dt><dd class="note">'
            f'{_e(r["status_group_basis"])}</dd>'
            + (''.join(f'<dt>{_e(k)}</dt><dd class="mono">{_e(_cut(v, 300))}</dd>'
                       for k, v in lifecycle) or
               '<dt>исход</dt><dd><span class="badge b-unk">в источнике не записан</span></dd>')
            + (f'<dt>история статусов</dt><dd class="mono">'
               f'{_e(" · ".join(trail))}</dd>' if trail else '')
            + f'<dt>источник записи</dt><dd class="mono">{_e(r["source"]["path"])}</dd>'
              f'</dl></details></div>')
    out.append('</div></div>')
    out.append(f'<h3>Производные кандидаты Director OS ({len(candidates)})</h3>')
    if not candidates:
        out.append('<div class="empty">Производных кандидатов нет.</div>')
    for c in candidates:
        out.append(
            f'<div class="card"><div class="big"><code>{_e(c["id"])}</code> '
            f'<span class="badge b-unk">не карточка решения</span></div><dl class="kv">'
            f'<dt>наблюдаемый факт</dt><dd>{_e(c["observed_fact"])}</dd>'
            f'<dt>почему решение</dt><dd>{_e(c["why_a_decision_may_be_needed"])}</dd>'
            f'<dt>существующее правило</dt><dd>{_e(c["existing_rule"])}</dd>'
            f'<dt>что выяснить</dt><dd>{_e(c["what_must_still_be_found_out"])}</dd>'
            f'<dt>безопасный шаг</dt><dd>{_e(c["possible_next_safe_step"])}</dd>'
            f'<dt>критичность / срок</dt><dd>'
            f'<span class="badge b-unk">{_e(c["severity"])}</span> · '
            f'<span class="badge b-unk">{_e(c["deadline"])}</span></dd>'
            f'<dt>сделано</dt><dd>{_e(c["action_taken"])}</dd></dl></div>')
    return ''.join(out)


def _sources(portal, brief, available):
    out = ['<h2 id="sources">5. Система и источники</h2>',
           '<table><thead><tr><th>источник</th><th>назначение</th><th>доступен</th>'
           '<th>каноничность</th></tr></thead><tbody>']
    for s in portal['sources']:
        badge = ('<span class="badge b-ok">да</span>' if s['available']
                 else '<span class="badge b-warn">НЕТ</span>')
        out.append(f'<tr><td class="mono">{_e(s["id"])}</td><td>{_e(s["purpose"])}</td>'
                   f'<td>{badge}<div class="evi">{_e(s.get("observed_at"))}</div></td>'
                   f'<td class="note">{_e(s["canonicality_rule"])}</td></tr>')
    out.append('</tbody></table>')
    for s in portal['sources']:
        out.append(f'<details><summary>{_e(s["id"])} — формат, писатель, ограничения'
                   f'</summary><dl class="kv">'
                   f'<dt>путь</dt><dd class="mono">{_e(s["path"])}</dd>'
                   f'<dt>формат</dt><dd>{_e(s["format"])}</dd>'
                   f'<dt>кто пишет</dt><dd>{_e(s["written_by"])}</dd>'
                   f'<dt>область</dt><dd>{_e(s["scope"])}</dd>'
                   f'<dt>sha256</dt><dd class="mono">{_e(s.get("sha256"))}</dd>'
                   + ''.join(f'<dt>ограничение</dt><dd class="note">{_e(x)}</dd>'
                             for x in s['limits'])
                   + (f'<dt>следствие недоступности</dt><dd class="note">'
                      f'{_e(s.get("consequence"))}</dd>' if not s['available'] else '')
                   + '</dl></details>')
    errors = portal['extraction_errors']
    out.append(f'<h3>Ошибки извлечения ({len(errors)})</h3>')
    if not errors:
        out.append('<p class="note">Ошибок извлечения нет. Это отдельный факт от '
                   '«данных нет».</p>')
    for e in errors:
        out.append(f'<div class="card"><code>{_e(e["source"])}</code> — '
                   f'<span class="badge b-warn">{_e(e["error"])}</span>'
                   f'<p class="note">{_e(e["consequence"])}</p></div>')
    conflicts = portal['conflicts']
    out.append(f'<h3>Расхождения источников ({len(conflicts)})</h3>')
    if not conflicts:
        out.append('<p class="note">Расхождений не обнаружено.</p>')
    for c in conflicts:
        statements = ''.join(f'<li><code>{_e(s["source"])}</code>: {_e(s["says"])}</li>'
                             for s in c['statements'])
        subjects = c.get('subjects') or []
        out.append(f'<div class="card"><div class="big">{_e(c["id"])}</div>'
                   f'<p class="note">вид: {_e(c["kind"])} · каноничность: '
                   f'<span class="badge b-unk">{_e(c["authority"])}</span></p>'
                   f'<ul>{statements}</ul><p class="note">{_e(c["note"])}</p>'
                   + (f'<details><summary>предметы ({len(subjects)})</summary><ul>'
                      + ''.join(f'<li><code>{_e(x)}</code></li>' for x in subjects)
                      + '</ul></details>' if subjects else '') + '</div>')
    out.append('<h3>Карты и evidence рядом со страницей</h3><ul>'
               f'<li>{_link("portal_snapshot.json", available)} — все объекты портала '
               'с источниками</li>'
               f'<li>{_link("owner_briefing.json", available)} · '
               f'{_link("owner_briefing.md", available)} — сводка Phase 1</li>'
               f'<li>{_link("diff.json", available)} · '
               f'{_link("changes.md", available)} — доказуемые изменения</li>'
               f'<li>{_link("source_of_truth.json", available)} · '
               f'{_link("source_of_truth.md", available)} — карта источников правды</li>'
               f'<li>{_link("system_map.md", available)} — обзор системной карты</li>'
               f'<li>{_link("run_manifest.json", available)} — входы, хеши, проверки</li>'
               '</ul>')
    out.append('<h3>Времена наблюдения</h3><dl class="kv">')
    times = portal['observation_times']
    for key, label in (('machine_observed_at', 'машина наблюдена'),
                       ('briefing_generated_at', 'сводка собрана'),
                       ('extraction_finished_at', 'карточки извлечены')):
        out.append(f'<dt>{_e(label)}</dt><dd class="mono">{_e(times.get(key))}</dd>')
    out.append(f'</dl><p class="note">{_e(times["note"])}</p>')
    out.append('<h3>Границы утверждений портала</h3><ul>'
               + ''.join(f'<li>{_e(x)}</li>' for x in portal['limits']) + '</ul>')
    if brief:
        out.append('<ul>' + ''.join(f'<li>{_e(x)}</li>' for x in brief['claim_limits'])
                   + '</ul>')
    return ''.join(out)


def _sev_badge(sev):
    cls = {'CRITICAL': 'b-warn', 'WARNING': 'b-warn', 'INFO': 'b-unk'}.get(sev, 'b-unk')
    return f'<span class="badge {cls}">{_e(sev)}</span>'


def _authority(auth, available):
    """Section 6: where truth lives, and where reality differs from it.

    Read-only by construction: there is no Repair, Sync, Delete, Deploy, Restart or
    "accept drift" control anywhere in this section, and none is implied. A row states
    what the authority is, what was observed, and the evidence for the verdict.
    """
    if not auth:
        return ('<h2 id="authority">6. Источник правды и расхождения</h2>'
                '<div class="empty">Карта авторитетности не приложена к этому комплекту. '
                'Это НЕ значит, что расхождений нет.</div>')
    c = auth['counts']
    st = c['by_drift_status']
    drift_keys = ('MODIFIED', 'MISSING_IN_PRODUCTION', 'EXTRA_IN_PRODUCTION',
                  'MISSING_IN_ORIGIN', 'DECLARED_NOT_OBSERVED', 'OBSERVED_NOT_DECLARED',
                  'STALE')
    drift_total = sum(st.get(k, 0) for k in drift_keys)
    problems = [e for e in auth['entities'] if e['drift_status'] in drift_keys]
    out = ['<h2 id="authority">6. Источник правды и расхождения</h2>',
           '<p class="note">Где по правилам живёт истина и где живая система с ней '
           'расходится. Кнопок починки, синхронизации, удаления, деплоя, перезапуска и '
           '«принять расхождение» здесь нет — раздел только читает.</p>',
           '<div class="card"><dl class="kv">',
           f'<dt>Авторитетный коммит</dt><dd class="mono">'
           f'{_e(auth["authoritative_commit"][:12])}</dd>',
           f'<dt>Совпадает с авторитетом</dt><dd class="big">{st.get("IN_SYNC", 0)}</dd>',
           f'<dt>Расходится</dt><dd class="big">{drift_total}</dd>',
           f'<dt>из них лишнее в проде</dt><dd class="big">'
           f'{st.get("EXTRA_IN_PRODUCTION", 0)}</dd>',
           f'<dt>Правило каноничности не объявлено</dt><dd class="big">'
           f'{st.get("AUTHORITY_UNDEFINED", 0)}</dd>',
           f'<dt>Неизвестно</dt><dd class="big">{st.get("UNKNOWN", 0)}</dd>',
           f'<dt>Вне доставки по правилу / производное</dt><dd class="big">'
           f'{st.get("IGNORED", 0) + st.get("GENERATED", 0)}</dd>',
           f'<dt>Severity</dt><dd>' + ' · '.join(
               f'{_sev_badge(k)} {v}' for k, v in sorted(c['by_severity'].items())) + '</dd>',
           '</dl>',
           f'<p class="note">Файлов в авторитетном коммите (область синхронизации): '
           f'{c["files_in_authoritative_commit"]}. Совпавшие показаны одним объектом-'
           f'сводкой намеренно.</p>',
           f'<p class="evi">карта: {_link("authority_map.json", available)}</p></div>']

    out.append('<h3>Цепочка доставки — только чтение</h3><table><thead><tr>'
               '<th>шаг</th><th>откуда → куда</th><th>механизм</th><th>роль авторитета</th>'
               '<th>наблюдаемое</th></tr></thead><tbody>')
    for s in auth['delivery_chain']:
        observed = ' · '.join(f'{k}={v}' for k, v in (s['observed_state'] or {}).items())
        out.append(f'<tr><td>{s["step"]}</td>'
                   f'<td>{_e(s["from"])} → {_e(s["to"])}<div class="evi">'
                   f'{_e(s["direction"])}</div></td>'
                   f'<td class="mono">{_e(s["mechanism"])}</td>'
                   f'<td class="note">{_e(s["authority_role"])}</td>'
                   f'<td class="mono">{_e(observed)}</td></tr>')
    out.append('</tbody></table>')

    types = sorted({e['entity_type'] for e in problems})
    statuses = sorted({e['drift_status'] for e in problems})
    authorities = sorted({e['authority_status'] for e in problems})
    sevs = sorted({e['severity'] for e in problems})
    out += [f'<h3>Расхождения ({len(problems)})</h3>',
            '<div id="authority-scope">',
            _controls('authority-scope',
                      [('atype', 'Тип объекта', types), ('astatus', 'Расхождение', statuses),
                       ('aauth', 'Каноничность', authorities), ('asev', 'Severity', sevs)],
                      [('apath', 'по объекту'), ('astatus', 'по расхождению'),
                       ('asev', 'по severity')]),
            '<div data-role="list">']
    if not problems:
        out.append('<div class="empty">Расхождений не обнаружено. Это отдельный факт от '
                   '«мы не смотрели» — смотрите сводку выше и ограничения ниже.</div>')
    for e in problems:
        ev = ''.join(f'<li>{_e(x["kind"])}: {_e(x["detail"])}'
                     + (f'<div class="evi mono">{_e(x["command"])}</div>'
                        if x.get('command') else '') + '</li>'
                     for x in e['evidence'])
        statements = ''.join(f'<li><code>{_e(s["source"])}</code>: {_e(s["says"])}</li>'
                             for s in (e.get('statements') or []))
        observed = ''.join(f'<dt>{_e(k)}</dt><dd class="mono">{_e(_cut(v, 200))}</dd>'
                           for k, v in (e.get('observed') or {}).items())
        hay = ' '.join(str(x).lower() for x in
                       (e['entity_id'], e['path'], e['drift_status'], e['severity'],
                        e['entity_type']))
        out.append(
            f'<div class="row" data-id="{_e(e["entity_id"])}" data-hay="{_e(hay)}" '
            f'data-atype="{_e(e["entity_type"])}" data-astatus="{_e(e["drift_status"])}" '
            f'data-aauth="{_e(e["authority_status"])}" data-asev="{_e(e["severity"])}" '
            f'data-apath="{_e(e["path"].lower())}">'
            f'<div class="rowhead">{_sev_badge(e["severity"])}'
            f'<span class="badge b-unk">{_e(e["drift_status"])}</span>'
            f'<span class="rowtitle mono">{_e(_cut(e["path"], 150))}</span></div>'
            f'<details><summary>где должен жить, что наблюдается, evidence</summary>'
            f'<dl class="kv">'
            f'<dt>тип объекта</dt><dd>{_e(e["entity_type"])}</dd>'
            f'<dt>объявленный источник</dt><dd>{_e(e["declared_source"])}</dd>'
            f'<dt>АВТОРИТЕТНЫЙ источник</dt><dd>{_e(e["authoritative_source"])}</dd>'
            f'<dt>наблюдаемый источник</dt><dd>{_e(e["observed_source"])}</dd>'
            f'<dt>производный источник</dt><dd>{_e(e["derived_source"])}</dd>'
            f'<dt>статус каноничности</dt><dd>'
            f'<span class="badge b-unk">{_e(e["authority_status"])}</span></dd>'
            f'<dt>чем установлено</dt><dd class="note">'
            f'{_e(e["authority_established_by"])}</dd>'
            f'<dt>ограничение</dt><dd class="note">{_e(e["authority_limit"])}</dd>'
            f'<dt>есть в origin</dt><dd>{_e(e["origin_present"])}</dd>'
            f'<dt>есть в проде</dt><dd>{_e(e["production_present"])}</dd>'
            f'<dt>почему такой статус</dt><dd class="note">{_e(e["severity_basis"])}</dd>'
            f'<dt>наблюдение снято</dt><dd class="mono">{_e(e["observed_at"])}</dd>'
            + observed + '</dl>'
            + (f'<h3>Что говорит каждый источник</h3><ul>{statements}</ul>'
               if statements else '')
            + f'<h3>Evidence</h3><ul>{ev}</ul></details></div>')
    out.append('</div></div>')
    out.append('<details><summary>Модель авторитетности по типам объектов</summary>'
               '<table><thead><tr><th>тип</th><th>авторитет</th><th>чем установлено</th>'
               '<th>ограничение</th></tr></thead><tbody>'
               + ''.join(
                   f'<tr><td class="mono">{_e(k)}</td>'
                   f'<td>{_e(v["authoritative_source"])}</td>'
                   f'<td class="note">{_e(v["established_by"])}</td>'
                   f'<td class="note">{_e(v["limit"])}</td></tr>'
                   for k, v in sorted(auth['authority_model'].items()))
               + '</tbody></table></details>')
    out.append('<h3>Границы этой карты</h3><ul>'
               + ''.join(f'<li>{_e(x)}</li>' for x in auth['limits']) + '</ul>')
    return ''.join(out)


def _n(value, unit=''):
    """Число или честное «не измерено». Ноль и пустота — разные ответы (инв. #17)."""
    if value is None or value == '':
        return '<span class="note">не измерено</span>'
    return f'{_e(value)}{_e(unit)}'


def _rel_card(f):
    """Карточка находки: восемь вопросов владельца, и ни одного придуманного ответа."""
    tasks = f.get('linked_tasks') or []
    explicit = [t for t in tasks if t.get('relation') == 'EXPLICIT_LINK']
    mentions = [t for t in tasks if t.get('relation') == 'MENTION_MATCH']
    rows = lambda items: '<ul>' + ''.join(  # noqa: E731
        f'<li class="mono">{_e(t["task"])}<div class="evi">{_e(t["basis"])}</div></li>'
        for t in items) + '</ul>'
    task_html = ''
    if explicit:
        task_html += rows(explicit)
    if mentions:
        task_html += ('<div class="note">Возможная связанная задача (совпадение по '
                      'упоминанию)</div>' + rows(mentions))
    if not tasks:
        task_html = ('<span class="note">Нет связанной задачи</span>'
                     '<div class="evi">карточка не заводится этим разделом</div>')
    elif not explicit:
        task_html = ('<span class="note">Объявленной связи нет — только совпадение по '
                     'упоминанию</span>' + task_html)
    age = f.get('source_age_hours')
    age_html = ('<span class="note">не измерено</span>' if age is None
                else (f'{age / 24:.1f} сут назад' if age > 48 else f'{age:.1f} ч назад'))
    freshness = f.get('freshness')
    silent = freshness in ('STALE', 'UNKNOWN')
    badge = {'STALE': 'источник просрочен',
             'UNKNOWN': 'свежесть не измерена'}.get(freshness, '')
    ev = ''.join(f'<li>{_e(x.get("kind"))}: {_e(_cut(x.get("detail"), 300))}'
                 + (f'<div class="evi mono">{_e(x.get("where"))}</div>'
                    if x.get('where') else '') + '</li>'
                 for x in f.get('evidence') or [])
    hay = ' '.join(str(x).lower() for x in
                   (f['finding_id'], f['affected_entity'], f['title'], f['severity'],
                    f['classification'], f['category'], f['status'], str(freshness),
                    ' '.join(f.get('sources') or [])))
    count = f.get('occurrence_count')
    rcount = f'{count:06d}' if isinstance(count, int) else ''
    return (
        f'<div class="row" data-id="{_e(f["finding_id"])}" data-hay="{_e(hay)}" '
        f'data-rsev="{_e(f["severity"])}" data-rclass="{_e(f["classification"])}" '
        f'data-rcat="{_e(f["category"])}" data-rstatus="{_e(f["status"])}" '
        f'data-rentity="{_e(f["affected_entity"].lower())}" '
        f'data-rfresh="{_e(freshness)}" '
        f'data-rlast="{_e(f.get("last_seen") or "")}" data-rcount="{rcount}">'
        f'<div class="rowhead">{_sev_badge(f["severity"])}'
        f'<span class="badge b-unk">{_e(f["classification"])}</span>'
        + (f'<span class="badge b-warn">{_e(badge)}</span>' if silent else '')
        + f'<span class="rowtitle">{_e(_cut(f["title"], 140))}</span></div>'
        f'<details><summary>что, где, сейчас, почему мы так считаем</summary>'
        f'<dl class="kv">'
        f'<dt>ЧТО</dt><dd>{_e(f["title"])}</dd>'
        f'<dt>ГДЕ</dt><dd class="mono">{_e(f["affected_entity"])}</dd>'
        f'<dt>СЕЙЧАС</dt><dd>{_e(f["status"])} · {_e(f["severity"])}'
        + ('<div class="evi">источник в последний раз говорил ' + age_html
           + ' — «активно» означает «источник не отзывал», а не «проверено сию минуту»'
             '</div>' if silent else '') + '</dd>'
        + f'<dt>свежесть источника</dt><dd>{_e(freshness)}'
        f'<div class="evi">{_e(f.get("freshness_rule") or "")}</div></dd>'
        + (f'<dt>авторитет по этому предмету</dt><dd class="mono">'
           f'{_e(f["authoritative_source"])}</dd>'
           if f.get('authoritative_source') else '')
        + f'<dt>ПОЧЕМУ МЫ ТАК СЧИТАЕМ</dt><dd class="note">'
        f'{_e(f["classification_reason"])}</dd>'
        f'<dt>КОГДА ПОСЛЕДНИЙ РАЗ ВИДЕЛИ</dt><dd class="mono">'
        f'{_n(f.get("last_seen"))}</dd>'
        f'<dt>впервые</dt><dd class="mono">{_n(f.get("first_seen"))}</dd>'
        f'<dt>СКОЛЬКО РАЗ</dt><dd>{_n(count)}'
        + (f'<div class="evi">{_e(f["occurrence_basis"])}</div>'
           if f.get('occurrence_basis') else
           '<div class="evi">ни один доступный источник не считает повторения по этому '
           'предмету — это «не считали», а не «повторений нет»</div>') + '</dd>'
        f'<dt>ИСТОЧНИК</dt><dd class="mono">{_e(", ".join(f.get("sources") or []))}'
        + (f'<div class="evi">подтверждено также: '
           f'{_e(", ".join(f["corroborated_by"]))} — подтверждение не является '
           f'повторением</div>' if f.get('corroborated_by') else '') + '</dd>'
        f'<dt>СВЯЗАННАЯ ЗАДАЧА</dt><dd>{task_html}</dd>'
        f'<dt>тип находки</dt><dd class="mono">{_e(f["finding_type"])}</dd>'
        f'</dl><h3>Evidence</h3><ul>{ev}</ul></details></div>')


def _rel_group(title, findings, empty):
    if not findings:
        return f'<h3>{_e(title)}</h3><div class="empty">{_e(empty)}</div>'
    return (f'<h3>{_e(title)} ({len(findings)})</h3>'
            + ''.join(_rel_card(f) for f in findings))


def _reliability(rel, available):
    """Раздел 7: что сломано, что деградирует, что повторяется — и чем доказано.

    Кнопок Fix, Repair, Restart, Delete, Sync, Deploy, Retry, Resolve, Acknowledge и
    Create Task здесь нет и не подразумевается: раздел только читает. Задача не заводится
    даже там, где связи с карточкой не нашлось — «нет связанной задачи» это факт, а не
    приглашение.
    """
    if not rel:
        return ('<h2 id="reliability">7. Надёжность и проблемы</h2>'
                '<div class="empty">Снимок надёжности не приложен к этому комплекту. '
                'Это НЕ значит, что всё исправно.</div>')
    c = rel['counts']
    f = rel['findings']
    confirmed = [x for x in f if x['status'] == 'ACTIVE_CONFIRMED']
    unverified = [x for x in f if x['status'] == 'ACTIVE_UNVERIFIED']
    # «Требует внимания сейчас» — ТОЛЬКО подтверждённое свежим источником. Запись,
    # которая держится лишь на том, что источник её не отзывал, живёт ниже отдельным
    # блоком: она не скрыта, но и не выдана за проверенную.
    attention = sorted((x for x in confirmed if x['severity'] in ('CRITICAL', 'WARNING')),
                       key=lambda x: ({'CRITICAL': 0, 'WARNING': 1}[x['severity']],
                                      x['finding_id']))
    overdue = sorted((x for x in unverified if x['freshness'] == 'STALE'),
                     key=lambda x: x['finding_id'])
    unmeasured = sorted((x for x in unverified if x['freshness'] != 'STALE'),
                        key=lambda x: x['finding_id'])
    problems = sorted((x for x in f if x['classification'] == 'PROBLEM_CANDIDATE'),
                      key=lambda x: (-(x['occurrence_count'] or 0), x['finding_id']))
    incidents = sorted((x for x in f if x['classification'] == 'INCIDENT'
                        and x['status'] == 'ACTIVE_CONFIRMED'),
                       key=lambda x: (x.get('last_seen') or '', x['finding_id']),
                       reverse=True)
    conditions = [x for x in f if x['classification'] == 'CONDITION']
    stale = [x for x in f if x['finding_type'] == 'stale_artifact']
    unknown = [x for x in f if x['classification'] == 'UNKNOWN'
               or x['status'] == 'UNKNOWN']
    by_class = c['by_classification']

    out = ['<h2 id="reliability">7. Надёжность и проблемы</h2>',
           '<p class="note">Что сломано, что деградирует, что устарело, что повторяется и '
           'где расхождение — по уже существующим наблюдениям. Раздел ничего не чинит, '
           'не перезапускает, не синхронизирует и не заводит задач: кнопок действий здесь '
           'нет намеренно. Причина (root cause) не устанавливается нигде.</p>',
           '<div class="card"><dl class="kv">',
           f'<dt>CRITICAL подтверждённых сейчас</dt><dd class="big">'
           f'{c["critical_confirmed_now"]}</dd>',
           f'<dt>CRITICAL без подтверждения</dt><dd class="big">'
           f'{c["critical_unverified"]}</dd>',
           f'<dt>WARNING подтверждённых сейчас</dt><dd class="big">'
           f'{c["warning_confirmed_now"]}</dd>',
           f'<dt>INCIDENTS</dt><dd class="big">{by_class.get("INCIDENT", 0)}</dd>',
           f'<dt>PROBLEM CANDIDATES</dt><dd class="big">'
           f'{by_class.get("PROBLEM_CANDIDATE", 0)}</dd>',
           f'<dt>STALE</dt><dd class="big">{len(stale)}</dd>',
           f'<dt>UNKNOWN</dt><dd class="big">{len(unknown)}</dd>',
           f'<dt>Severity не объявлена источником</dt><dd class="big">'
           f'{c["unknown_severity"]}</dd>',
           f'<dt>Требует перепроверки (источник не подтверждает)</dt><dd class="big">'
           f'{c["active_unverified"]}</dd>',
           '</dl>',
           f'<p class="note">Источников прочитано {c["sources_read"]}, недоступно '
           f'{c["sources_unavailable"]}; собственный срок годности объявлен у '
           f'{c["sources_with_declared_slo"]}, у {c["sources_freshness_unknown"]} свежесть '
           f'НЕ измерена. Объявленная связь с задачей: {c["explicit_task_links"]}, только '
           f'совпадение по упоминанию: {c["mention_only_matches"]}, без связи: '
           f'{c["no_task_relation"]} — задачи этим разделом НЕ создаются.</p>',
           f'<p class="note">Срок годности берётся из '
           f'<span class="mono">{_e(rel["freshness_rule_source"])}</span></p>',
           f'<p class="evi">снимок: '
           f'{_link("reliability_snapshot.json", available)}</p></div>']

    out.append(_rel_group('Требует внимания сейчас', attention,
                          'подтверждённых свежим источником записей с объявленной severity '
                          'нет. Это НЕ «всё исправно»: ниже лежат записи, которые источник '
                          'не отзывал, но и не подтверждает.'))
    out.append('<h3>Источник давно не обновлялся — состояние требует перепроверки '
               f'({len(overdue) + len(unmeasured)})</h3>'
               '<p class="note">Эти записи никуда не делись и не закрыты. Их единственное '
               'основание — «источник ещё не отозвал»; подтвердить их «сейчас» нечем. '
               'Молчание источника не означает, что состояние ушло.</p>')
    out.append(_rel_group('Источник просрочил собственный объявленный срок', overdue,
                          'просроченных источников нет.'))
    out.append(_rel_group('Срок годности источника не объявлен — свежесть НЕ измерена',
                          unmeasured,
                          'источников без объявленного срока нет.'))
    out.append(_rel_group('Повторяющиеся и устойчивые', problems,
                          'ни по одному предмету повторяемость или длительность не '
                          'ИЗМЕРЕНЫ. Это «не считали», а не «не повторяется».'))
    out.append(_rel_group('Недавние incidents', incidents[:12],
                          'активных единичных сбоев с отметкой времени не найдено.'))

    out.append(f'<h3>Архитектурные условия ({len(conditions)})</h3>')
    groups = {}
    for x in conditions:
        groups.setdefault(x['finding_type'], []).append(x)
    out.append('<table><thead><tr><th>условие</th><th>сколько</th>'
               '<th>что это значит</th></tr></thead><tbody>')
    meaning = {
        'retired_code_in_production': 'origin файл удалил, а checkout удалить не может — '
                                      'он остаётся в проде и назван синхронизацией',
        'local_only_code': 'файл есть только здесь и не отслеживается git',
        'code_drift': 'дерево, из которого работает флот, расходится с авторитетом',
        'authority_undefined': 'правило каноничности для объекта не объявлено',
        'declared_not_observed': 'объявлено, но в живой системе не наблюдается',
        'observed_not_declared': 'наблюдается, но ни одним реестром не объявлено',
        'stale_artifact': 'артефакт старше собственного порога свежести',
        'unknown_observation': 'наблюдение не удалось классифицировать',
        'fleet_parity': 'состав флота расходится с объявленным',
    }
    for kind, items in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out.append(f'<tr><td class="mono">{_e(kind)}</td><td class="big">{len(items)}</td>'
                   f'<td class="note">{_e(meaning.get(kind, "—"))}</td></tr>')
    out.append('</tbody></table>')

    sevs = sorted({x['severity'] for x in f})
    classes = sorted({x['classification'] for x in f})
    cats = sorted({x['category'] for x in f})
    states = sorted({x['status'] for x in f})
    freshes = sorted({x['freshness'] for x in f})
    out += [f'<h3>Все находки ({len(f)})</h3>',
            '<div id="reliability-scope">',
            _controls('reliability-scope',
                      [('rsev', 'Severity', sevs), ('rclass', 'Классификация', classes),
                       ('rcat', 'Категория', cats), ('rstatus', 'Состояние', states),
                       ('rfresh', 'Свежесть источника', freshes)],
                      [('rsev', 'по severity'), ('rlast', 'по последнему наблюдению'),
                       ('rcount', 'по числу наблюдений'), ('rentity', 'по объекту')]),
            '<div data-role="list">']
    out += [_rel_card(x) for x in f]
    out.append('</div></div>')

    out.append('<details><summary>Источники надёжности и что каждый из них меряет'
               '</summary><table><thead><tr><th>источник</th><th>что меряет</th>'
               '<th>род</th><th>свежесть</th><th>severity</th><th>время</th>'
               '<th>устойчивый id</th><th>считает повторы</th><th>состояние</th>'
               '</tr></thead><tbody>')
    for s in rel['sources']:
        yes = lambda v: ('да' if v else ('нет' if v is False else '—'))  # noqa: E731
        out.append(f'<tr><td class="mono">{_e(s["source"])}</td>'
                   f'<td class="note">{_e(s.get("measures") or "—")}</td>'
                   f'<td>{_e(s.get("basis") or "—")}'
                   + ('<div class="evi">пересобираемый производный артефакт: источником '
                      'правды не является</div>' if s.get('rebuildable_artifact') else '')
                   + '</td>'
                   f'<td>{_e(s.get("freshness"))}'
                   f'<div class="evi">{_e(_cut(s.get("freshness_rule") or "", 160))}</div>'
                   f'</td>'
                   f'<td>{yes(s.get("has_severity"))}</td>'
                   f'<td>{yes(s.get("has_timestamps"))}</td>'
                   f'<td>{yes(s.get("has_stable_id"))}</td>'
                   f'<td>{yes(s.get("counts_occurrences"))}</td>'
                   f'<td><span class="badge b-unk">{_e(s["status"])}</span>'
                   f'<div class="evi">{_e(s.get("limit") or "")}</div></td></tr>')
    out.append('</tbody></table></details>')
    out.append('<h3>Границы этого раздела</h3><ul>'
               + ''.join(f'<li>{_e(x)}</li>' for x in rel['limits']) + '</ul>')
    return ''.join(out)


_WORK_STATE_LABELS = {
    'NOT_STARTED': 'не начато', 'IN_PROGRESS': 'в работе', 'BLOCKED': 'заблокировано',
    'WAITING_OWNER': 'ждёт владельца',
    'DONE_ACCEPTANCE_UNCONFIRMED': 'завершено, приёмка не подтверждена',
    'DONE_ACCEPTANCE_UNKNOWN': 'завершено, статус приёмки не измерен',
    'DONE_ACCEPTANCE_NOT_APPLICABLE': 'завершено, отдельная приёмка не требуется',
    'ACCEPTED': 'принято', 'UNKNOWN': 'статус неизвестен',
}
_ACCEPT_LABELS = {
    'CONFIRMED': 'подтверждена', 'NOT_CONFIRMED': 'НЕ подтверждена',
    'NOT_APPLICABLE': 'правило не относится', 'UNKNOWN': 'не измерено',
}


def _who(w):
    """Кто исполняет — ровно по улике. Заявка цикла или сессии агентом НЕ называется."""
    if not w.get('claimed_by'):
        return '<span class="note">не измерено</span>'
    kind = w.get('claim_kind')
    label = {'CYCLE': 'цикл', 'SESSION': 'сессия', 'PID': 'процесс',
             'AGENT_LABEL': 'агент (подтверждён)',
             'UNVERIFIED_LABEL': 'похоже на ярлык агента, НЕ подтверждён'}.get(kind, kind)
    return (f'<span class="mono">{_e(w["claimed_by"])}</span> '
            f'<span class="badge b-unk">{_e(label)}</span>'
            f'<div class="evi">{_e(w.get("claim_reason") or "")}</div>')


def _work_card(w, brief=False):
    """Карточка работы: одиннадцать вопросов владельца, и ни одного придуманного ответа.

    ``brief`` — та же строка в краткой форме, для завершённых работ в общем списке. Она
    несёт ВСЕ признаки фильтрации и по-прежнему раскрывается, но показывает четыре поля
    вместо одиннадцати. Причина измеренная, а не вкусовая: работ 1577, из них больше
    девяти сотен — закрытые записи KANBAN трёхмесячной давности, и полная форма у каждой
    давала страницу в 7,8 МБ. Полная карточка живой работы никуда не девается: она в
    блоках выше, где владелец её и ищет.
    """
    ev = lambda items: ''.join(  # noqa: E731
        f'<li>{_e(x.get("kind"))}: {_e(_cut(x.get("detail"), 260))}</li>'
        for x in (items or [])[:6])
    explicit = [r for r in w.get('related_findings') or []
                if r['relation'] == 'EXPLICIT_LINK']
    mention = [r for r in w.get('related_findings') or []
               if r['relation'] == 'MENTION_MATCH']
    hay = ' '.join(str(x).lower() for x in
                   (w['work_id'], w['title'], str(w['source_state']),
                    w['owner_view_state'], w['work_type'], w['acceptance_status'],
                    str(w.get('claimed_by') or ''), str(w.get('owner_role') or '')))
    head = (
        f'<div class="row" data-id="{_e(w["work_id"])}" data-hay="{_e(hay)}" '
        f'data-wview="{_e(w["owner_view_state"])}" '
        f'data-wsource="{_e(str(w["source_state"]))}" '
        f'data-wtype="{_e(w["work_type"])}" '
        f'data-wowner="{_e(w.get("owner_role") or "не измерено")}" '
        f'data-waccept="{_e(w["acceptance_status"])}" '
        f'data-wapplic="{_e(w.get("acceptance_applicability") or "UNKNOWN")}" '
        f'data-wblock="{_e(w["blocker_status"])}" '
        f'data-wdecision="{"да" if w.get("owner_decision_needed") else "нет"}" '
        f'data-wfinding="{"объявленная" if explicit else ("упоминание" if mention else "нет")}" '
        f'data-wlast="{_e(w.get("last_activity_at") or "")}" '
        f'data-wstarted="{_e(w.get("started_at") or "")}">'
        f'<div class="rowhead">'
        f'<span class="badge b-unk">{_e(_WORK_STATE_LABELS[w["owner_view_state"]])}</span>'
        + (f'<span class="badge b-warn">приёмка '
           f'{_e(_ACCEPT_LABELS[w["acceptance_status"]])}</span>'
           if w['acceptance_status'] == 'NOT_CONFIRMED' else '')
        + ('<span class="badge b-warn">приёмка есть, состояние не закрыто</span>'
           if w.get('acceptance_state_conflict') else '')
        + f'<span class="rowtitle">{_e(_cut(w["title"], 130))}</span></div>')

    if brief:
        return (head
                + '<details><summary>статус, приёмка, источник</summary><dl class="kv">'
                + f'<dt>СТАТУС</dt><dd>{_e(_WORK_STATE_LABELS[w["owner_view_state"]])}'
                  f'<div class="evi">исходное состояние: <span class="mono">'
                  f'{_e(str(w["source_state"]))}</span> · {_e(w["mapping_reason"])}</div>'
                  '</dd>'
                + f'<dt>ПРИЁМКА</dt><dd>{_e(_ACCEPT_LABELS[w["acceptance_status"]])}'
                  f'<div class="evi">применимость: '
                  f'{_e(w.get("acceptance_applicability"))}</div>'
                  f'<ul>{ev(w["acceptance_evidence"])}</ul></dd>'
                + f'<dt>КОГДА БЫЛА АКТИВНОСТЬ</dt><dd class="mono">'
                  f'{_n(w.get("last_activity_at"))}</dd>'
                + f'<dt>ИСТОЧНИК</dt><dd class="mono">{_e(w["source"])}'
                  f'<div class="evi">{_e(w["work_id"])}</div></dd>'
                + '</dl></details></div>')

    outputs = ''.join(f'<li class="mono">{_e(o["path"])}'
                      f'<div class="evi">{_e(o["basis"])}</div></li>'
                      for o in (w.get('output_refs') or [])[:8])
    problems = ''
    if explicit:
        problems += '<ul>' + ''.join(f'<li class="mono">{_e(r["finding"])}'
                                     f'<div class="evi">{_e(r["basis"])}</div></li>'
                                     for r in explicit) + '</ul>'
    if mention:
        problems += ('<div class="note">Возможная связь (совпадение по упоминанию)</div>'
                     '<ul>' + ''.join(f'<li class="mono">{_e(r["finding"])}</li>'
                                      for r in mention[:4]) + '</ul>')
    if not problems:
        problems = '<span class="note">не измерено</span>'
    return (
        head
        + '<details><summary>что делаем, кто, что мешает, приёмка</summary><dl class="kv">'
        + f'<dt>ЧТО ДЕЛАЕМ</dt><dd>{_e(w["title"])}</dd>'
        + f'<dt>СТАТУС</dt><dd>{_e(_WORK_STATE_LABELS[w["owner_view_state"]])}'
          f'<div class="evi">исходное состояние: <span class="mono">'
          f'{_e(str(w["source_state"]))}</span> · {_e(w["mapping_reason"])}</div></dd>'
        + f'<dt>КТО ОТВЕЧАЕТ</dt><dd>{_n(w.get("owner_role"))}'
        + (f'<div class="evi">{_e(w["owner_evidence"][0]["detail"])}</div>'
           if w.get('owner_evidence') else '') + '</dd>'
        + f'<dt>КТО СЕЙЧАС ИСПОЛНЯЕТ</dt><dd>{_who(w)}</dd>'
        + f'<dt>КОГДА БЫЛА АКТИВНОСТЬ</dt><dd class="mono">'
          f'{_n(w.get("last_activity_at"))}</dd>'
        + f'<dt>ЧТО МЕШАЕТ</dt><dd>{_e(w["blocker_status"])}'
        + (f'<ul>{ev(w["blocker_evidence"])}</ul>' if w.get('blocker_evidence')
           else '<div class="evi">улик блокера нет; «давно не менялось» блокером здесь '
                'не считается</div>') + '</dd>'
        + '<dt>ЧТО ПОЛУЧЕНО</dt><dd>'
        + (f'<ul>{outputs}</ul>' if outputs else '<span class="note">не измерено</span>')
        + '</dd>'
        + f'<dt>ПРИЁМКА</dt><dd>{_e(_ACCEPT_LABELS[w["acceptance_status"]])}'
          f'<div class="evi">применимость: '
          f'{_e(w.get("acceptance_applicability"))}</div>'
          f'<ul>{ev(w["acceptance_evidence"])}</ul></dd>'
        + '<dt>КАКОЕ РЕШЕНИЕ НУЖНО ОТ ВЛАДЕЛЬЦА</dt><dd>'
        + (_e(_cut(w["owner_decision_needed"], 400)) if w.get('owner_decision_needed')
           else '<span class="note">не требуется по состоянию карточки</span>') + '</dd>'
        + f'<dt>СВЯЗАННЫЕ ПРОБЛЕМЫ</dt><dd>{problems}</dd>'
        + f'<dt>ИСТОЧНИК</dt><dd class="mono">{_e(w["source"])}'
          f'<div class="evi">{_e(w["work_id"])}</div></dd>'
        + (f'<dt>решения</dt><dd class="mono">{_e(", ".join(w["related_decisions"]))}</dd>'
           if w.get('related_decisions') else '')
        + '</dl></details></div>')


def _work_group(title, items, empty, limit=None):
    shown = items if limit is None else items[:limit]
    if not items:
        return f'<h3>{_e(title)}</h3><div class="empty">{_e(empty)}</div>'
    tail = ('' if limit is None or len(items) <= limit else
            f'<p class="note">показаны первые {limit} из {len(items)}; остальные — в '
            'полном списке ниже с теми же фильтрами</p>')
    return (f'<h3>{_e(title)} ({len(items)})</h3>'
            + ''.join(_work_card(w) for w in shown) + tail)


def _work_view(work, available):
    """Раздел 8: что строится, кем, где застряло, что ждёт владельца.

    Кнопок Start, Stop, Assign, Reassign, Approve, Reject, Retry, Pause, Resume, Create
    task, Resolve и Deploy здесь нет и не подразумевается: раздел только читает. Ни одна
    карточка не создаётся и не двигается.
    """
    if not work:
        return ('<h2 id="work">8. Разработка и работа</h2>'
                '<div class="empty">Снимок работы не приложен к этому комплекту. Это НЕ '
                'значит, что работы нет.</div>')
    c = work['counts']
    idn = work['identity']
    items = work['work']
    by_view = lambda name: [w for w in items if w['owner_view_state'] == name]  # noqa: E731
    recent = lambda seq: sorted(  # noqa: E731
        seq, key=lambda w: (w.get('last_activity_at') or '', w['work_id']), reverse=True)

    out = ['<h2 id="work">8. Разработка и работа</h2>',
           '<p class="note">Что сейчас строится, кем, где застряло, что уже закончено и '
           'что ждёт решения владельца. Раздел ничего не запускает, не назначает, не '
           'принимает и не заводит задач: кнопок действий здесь нет намеренно. Состояния '
           'взяты из определений трекеров, а не придуманы.</p>',
           '<div class="card"><dl class="kv">',
           f'<dt>В работе</dt><dd class="big">{c["in_progress"]}</dd>',
           f'<dt>Заблокировано</dt><dd class="big">{c["blocked"]}</dd>',
           f'<dt>Ждёт владельца</dt><dd class="big">{c["waiting_owner"]}</dd>',
           f'<dt>Принято</dt><dd class="big">{c["accepted"]}</dd>',
           f'<dt>Завершено, приёмка не подтверждена</dt><dd class="big">'
           f'{c["done_acceptance_unconfirmed"]}</dd>',
           f'<dt>Завершено, статус приёмки не измерен</dt><dd class="big">'
           f'{c["done_acceptance_unknown"]}</dd>',
           f'<dt>Завершено, отдельная приёмка не требуется</dt><dd class="big">'
           f'{c["done_acceptance_not_applicable"]}</dd>',
           f'<dt>Статус неизвестен</dt><dd class="big">{c["unknown_state"]}</dd>',
           '</dl>',
           f'<p class="note"><b>Записей в этом снимке {c["source_records"]}</b>: '
           f'{_e(str(idn["tracker"]["source_record_count"]))} записей трекера и '
           f'{_e(str(idn["kanban"]["unique_identifier_count"]))} идентификаторов KANBAN '
           f'(сырых записей там {_e(str(idn["kanban"]["source_record_count"]))}, '
           f'{_e(str(idn["kanban"]["duplicate_identifiers"]))} повторов одного id). '
           f'<b>Уникальное число работ НЕ ИЗМЕРЕНО</b>: {_e(idn["proven_unique_reason"])} '
           f'Перекрёстных ссылок без доказанного тождества: '
           f'{_e(str(idn["unresolved_identity_records"]))}; совпадений заголовков '
           f'{_e(str(idn["cross_source"]["title_only_matches"]))}, и тождеством они не '
           f'считаются ни при каком числе. Авторитет между реестрами: '
           f'{_e(idn["cross_source"]["authority_between_registries"])}.</p>',
           f'<p class="note">Источников прочитано {c["sources_read"]}, недоступно '
           f'{c["sources_unavailable"]}. Исполнительских заявок '
           f'{c["execution_claim_known"]}, из них НЕ агент {c["claim_not_an_agent"]}, '
           f'подтверждённых агентов {c["claim_is_a_verified_agent"]}. Расхождений '
           f'«приёмка подтверждена, а состояние не закрыто»: '
           f'{c["acceptance_state_conflicts"]}.</p>',
           f'<p class="evi">снимок: {_link("work_snapshot.json", available)}</p></div>']

    out.append(_work_group('Сейчас строится', recent(by_view('IN_PROGRESS')),
                           'ни одна работа не помечена как идущая.', limit=10))
    out.append(_work_group('Застряло и заблокировано', by_view('BLOCKED'),
                           'заблокированных работ по улике нет. «Давно не менялось» '
                           'блокером здесь не считается.'))
    out.append(_work_group('Ждёт моего решения', by_view('WAITING_OWNER'),
                           'карточек, чьё состояние прямо говорит «ждёт владельца», нет.'))
    conflicts = [w for w in items if w.get('acceptance_state_conflict')]
    out.append(_work_group('Завершено, приёмка НЕ подтверждена',
                           recent(by_view('DONE_ACCEPTANCE_UNCONFIRMED')),
                           'таких работ нет.', limit=10))
    out.append(_work_group('Завершено, статус приёмки не измерен',
                           recent(by_view('DONE_ACCEPTANCE_UNKNOWN')),
                           'таких работ нет.', limit=5))
    out.append(_work_group('Приёмка подтверждена, а состояние не закрыто', conflicts,
                           'расхождений между приёмкой и состоянием нет.', limit=10))
    out.append(_work_group('Недавно принято', recent(by_view('ACCEPTED')),
                           'подтверждённых приёмок нет.', limit=10))

    out.append('<h3>Кто чем занят</h3>'
               '<p class="note">Только по доказанной улике. Номер цикла, идентификатор '
               'сессии и pid — это НЕ агент, и здесь они так и подписаны.</p>'
               '<table><thead><tr><th>заявка</th><th>род</th><th>работ</th>'
               '<th>что это значит</th></tr></thead><tbody>')
    claims = {}
    for w in items:
        if w.get('claimed_by'):
            claims.setdefault((w['claimed_by'], w['claim_kind']), []).append(w)
    if not claims:
        out.append('<tr><td colspan="4" class="note">исполнительских заявок не найдено — '
                   'это «не измерено», а не «никто не работает»</td></tr>')
    for (who, kind), group in sorted(claims.items(), key=lambda kv: -len(kv[1]))[:20]:
        out.append(f'<tr><td class="mono">{_e(who)}</td>'
                   f'<td><span class="badge b-unk">{_e(kind)}</span></td>'
                   f'<td class="big">{len(group)}</td>'
                   f'<td class="note">'
                   f'{_e(work["claim_kind_definitions"].get(kind, ""))}</td></tr>')
    out.append('</tbody></table>')

    views = sorted({w['owner_view_state'] for w in items})
    sources_ = sorted({str(w['source_state']) for w in items})
    types = sorted({w['work_type'] for w in items})
    owners = sorted({w.get('owner_role') or 'не измерено' for w in items})
    accepts = sorted({w['acceptance_status'] for w in items})
    applic = sorted({w['acceptance_applicability'] for w in items})
    blocks = sorted({w['blocker_status'] for w in items})
    out += [f'<h3>Все работы ({len(items)})</h3>',
            '<div id="work-scope">',
            _controls('work-scope',
                      [('wview', 'Статус для владельца', views),
                       ('wsource', 'Исходное состояние', sources_),
                       ('wtype', 'Род работы', types),
                       ('wowner', 'Ответственный', owners),
                       ('waccept', 'Приёмка', accepts),
                       ('wapplic', 'Применимость приёмки', applic),
                       ('wblock', 'Блокер', blocks),
                       ('wdecision', 'Нужно решение владельца', ['да', 'нет']),
                       ('wfinding', 'Связь с надёжностью',
                        ['объявленная', 'упоминание', 'нет'])],
                      [('wlast', 'по последней активности'),
                       ('wstarted', 'по началу работы'),
                       ('wview', 'по статусу'), ('wowner', 'по ответственному')]),
            '<div data-role="list">']
    terminal = ('DONE_NOT_ACCEPTED', 'ACCEPTED')
    out += [_work_card(w, brief=w['owner_view_state'] in terminal)
            for w in items]
    out.append('</div></div>')

    out.append('<details><summary>Источники работы и что каждый из них может доказать'
               '</summary><table><thead><tr><th>источник</th><th>что представляет</th>'
               '<th>авторитет</th><th>род</th><th>владелец</th><th>состояние</th><th>завершение</th>'
               '<th>приёмка</th><th>блокер</th><th>результат</th><th>состояние чтения</th>'
               '</tr></thead><tbody>')
    yes = lambda v: ('да' if v else ('нет' if v is False else '—'))  # noqa: E731
    for s in work['sources']:
        out.append(f'<tr><td class="mono">{_e(s["source"])}</td>'
                   f'<td class="note">{_e(s.get("represents") or "—")}</td>'
                   f'<td><span class="badge b-unk">'
                   f'{_e(s.get("authority_status") or "—")}</span>'
                   f'<div class="evi">'
                   f'{_e(_cut(s.get("authority_quote") or "", 200))}</div></td>'
                   f'<td>{_e(s.get("basis") or "—")}'
                   + ('<div class="evi">пересобираемый производный артефакт</div>'
                      if s.get('rebuildable_artifact') else '')
                   + '</td>'
                   f'<td>{yes(s.get("can_prove_owner"))}</td>'
                   f'<td>{yes(s.get("can_prove_current_state"))}</td>'
                   f'<td>{yes(s.get("can_prove_completion"))}</td>'
                   f'<td>{yes(s.get("can_prove_acceptance"))}</td>'
                   f'<td>{yes(s.get("can_prove_blocker"))}</td>'
                   f'<td>{yes(s.get("can_prove_output"))}</td>'
                   f'<td><span class="badge b-unk">{_e(s["status"])}</span>'
                   f'<div class="evi">{_e(_cut(s.get("limit") or "", 140))}</div></td>'
                   f'</tr>')
    out.append('</tbody></table></details>')
    out.append('<h3>Границы этого раздела</h3><ul>'
               + ''.join(f'<li>{_e(x)}</li>' for x in work['limits']) + '</ul>')
    return ''.join(out)


_DIRECTOR_BLOCK_TITLES = {
    'owner_decisions': 'Нужно моё решение',
    'attention_now': 'Требует внимания сейчас',
    'current_work': 'Сейчас строится',
    'blocked': 'Заблокировано',
    'acceptance_attention': 'Приёмка требует внимания',
    'acceptance_not_measured': 'Статус приёмки не измерен',
    'system_drift': 'Системные расхождения',
    'unverified_state': 'Состояние не подтверждено',
}

_DIRECTOR_ORDER = ('owner_decisions', 'attention_now', 'current_work', 'blocked',
                   'acceptance_attention', 'acceptance_not_measured', 'system_drift',
                   'unverified_state')


def _director_item(it):
    ev = ''.join(f'<li>{_e(x.get("kind"))}: {_e(_cut(x.get("detail"), 260))}</li>'
                 for x in (it.get('evidence') or [])[:3])
    return (f'<div class="row">'
            f'<div class="rowhead"><span class="rowtitle">'
            f'{_e(_cut(it["title"], 120))}</span></div>'
            + (f'<div class="evi mono">{_e(_cut(it["entity"], 110))}</div>'
               if it.get('entity') else '')
            + f'<div class="note">{_e(_cut(it.get("detail") or "", 300))}</div>'
            f'<details><summary>чем доказано</summary>'
            f'<ul>{ev}</ul>'
            f'<p class="evi">слой: <span class="mono">{_e(it["source_layer"])}</span></p>'
            '</details></div>')


def _director(center):
    """Раздел 0: что владельцу нужно знать и решить сейчас.

    Собственной логики истины здесь нет: каждая строка приехала из нижнего слоя вместе со
    своей уликой и ссылкой на раздел, где она живёт целиком. Кнопок Approve, Reject,
    Start, Stop, Retry, Repair, Assign, Deploy и Create Task нет — только чтение и
    переходы. Общего балла здоровья нет намеренно.
    """
    if not center:
        return ('<h2 id="director">0. Центр директора</h2>'
                '<div class="empty">Центр не приложен к этому комплекту. Это НЕ значит, '
                'что решать нечего.</div>')
    state = center['system_state']
    cls = {'НОРМАЛЬНО': 'b-ok', 'ТРЕБУЕТ ВНИМАНИЯ': 'b-warn'}.get(state, 'b-unk')
    b = center['blocks']
    a = center['acceptance_summary']
    d = center['system_drift_summary']
    out = ['<h2 id="director">0. Центр директора</h2>',
           '<p class="note">Что нужно знать и решить сейчас. Экран ничего не запускает, '
           'не назначает и не принимает — он только показывает уже доказанное нижними '
           'слоями и ведёт туда, где это лежит целиком.</p>',
           '<div class="card"><dl class="kv">',
           f'<dt>Состояние системы</dt><dd><span class="badge {cls}">{_e(state)}</span>'
           f'<div class="evi">{_e(center["system_state_reason"])}</div></dd>',
           f'<dt>Нужно моё решение</dt><dd class="big">'
           f'{b["owner_decisions"]["count"]}</dd>',
           f'<dt>Требует внимания сейчас</dt><dd class="big">'
           f'{b["attention_now"]["count"]}</dd>',
           f'<dt>Сейчас строится</dt><dd class="big">{b["current_work"]["count"]}</dd>',
           f'<dt>Заблокировано</dt><dd class="big">{b["blocked"]["count"]}</dd>',
           '</dl>',
           f'<p class="note">{_e(center["health_score_note"])}</p></div>']

    for name in _DIRECTOR_ORDER:
        block = b[name]
        out.append(f'<h3>{_e(_DIRECTOR_BLOCK_TITLES[name])} ({block["count"]})</h3>')
        if name == 'acceptance_attention':
            out.append('<div class="card"><dl class="kv">'
                       f'<dt>приёмка применима, но НЕ подтверждена</dt>'
                       f'<dd class="big">{a["unconfirmed"]}</dd>'
                       f'<dt>расхождение: приёмка есть, состояние не закрыто</dt>'
                       f'<dd class="big">{a["conflict"]}</dd></dl>'
                       '<p class="note">Только это и есть вопросы к приёмке. Работы, к '
                       'которым правило приёмки не относится вовсе '
                       f'({a["not_applicable"]}), проблемой не считаются и сюда не '
                       'входят.</p></div>')
        if name == 'acceptance_not_measured':
            out.append('<div class="card"><p class="note">Показатель информационный: '
                       'ни одно правило приёмки не покрывает этот род работ, поэтому '
                       'её статус НЕ измерен. Это не долг и не нарушение — это '
                       'отсутствие правила, которое бы сюда смотрело.</p></div>')
        if name == 'unverified_state':
            u = center.get('unverified_summary') or {}
            out.append('<div class="card"><dl class="kv">'
                       f'<dt>записей без подтверждения</dt><dd class="big">'
                       f'{_n(u.get("count"))}</dd></dl>'
                       f'<p class="note">{_e(u.get("is_not_drift") or "")}</p></div>')
        if name == 'system_drift':
            out.append('<div class="card"><dl class="kv">'
                       f'<dt>расхождение доставки</dt><dd class="big">'
                       f'{_n(d.get("production_drift"))}</dd>'
                       f'<dt>каноничность не объявлена</dt><dd class="big">'
                       f'{_n(d.get("authority_undefined"))}</dd>'
                       '</dl><p class="note">'
                       + _e(d.get('excludes') or '') + '</p>'
                       + (f'<p class="evi">авторитетный коммит: '
                          f'<span class="mono">{_e(d.get("authoritative_commit"))}</span>'
                          f'</p>' if d.get('authoritative_commit') else '')
                       + '</div>')
        if block['items']:
            out += [_director_item(it) for it in block['items']]
        else:
            out.append(f'<div class="empty">{_e(block["empty_means"])}</div>')
        out.append(f'<p class="note">порядок: {_e(block["ordered_by"])} · '
                   f'<a href="{_e(section_href(block["show_all_anchor"].lstrip("#")))}">'
                   f'Показать все — '
                   f'{_e(block["show_all_label"])}</a></p>')

    out.append('<details><summary>Из каких слоёв собран этот экран</summary>'
               '<table><thead><tr><th>слой</th><th>состояние</th><th>снят</th>'
               '<th>digest</th></tr></thead><tbody>'
               + ''.join(
                   f'<tr><td class="mono">{_e(x["layer"])}</td>'
                   f'<td><span class="badge b-unk">{_e(x["status"])}</span>'
                   f'<div class="evi">{_e(x.get("note") or "")}</div></td>'
                   f'<td class="mono">{_e(x.get("generated_at") or "—")}</td>'
                   f'<td class="mono">{_e(x.get("digest") or "—")}</td></tr>'
                   for x in center['layers'])
               + '</tbody></table></details>')
    return ''.join(out)


_MODE_BADGE = {'REAL': 'b-warn', 'PAPER': 'b-ok', 'SHADOW': 'b-unk', 'FORECAST': 'b-unk',
               'RND': 'b-unk', 'UNKNOWN': 'b-unk'}


def _mode(mode):
    """Режим виден всегда и подписан словами: бумага не выдаётся за реальные деньги."""
    words = {'REAL': 'РЕАЛЬНЫЕ ДЕНЬГИ', 'PAPER': 'БУМАГА', 'SHADOW': 'ТЕНЬ',
             'FORECAST': 'ПРОГНОЗ', 'RND': 'R&D', 'UNKNOWN': 'РЕЖИМ НЕ ИЗМЕРЕН'}
    return (f'<span class="badge {_MODE_BADGE.get(mode, "b-unk")}">'
            f'{_e(words.get(mode, mode))}</span>')


def _inv_card(o):
    metrics = ''.join(f'<li class="mono">{_e(m.get("name"))}: {_e(m.get("value"))}'
                      f'<div class="evi">{_e(m.get("source"))}</div></li>'
                      for m in (o.get('performance_metrics') or [])[:6])
    limits = ''.join(f'<li>{_e(x.get("name"))}: {_e(_cut(str(x.get("detail")), 160))}'
                     f' — {_e(x.get("pass"))}</li>'
                     for x in (o.get('risk_limits') or [])[:6])
    ev = ''.join(f'<li>{_e(x.get("kind"))}: {_e(_cut(x.get("detail"), 300))}</li>'
                 for x in (o.get('evidence') or [])[:4])
    # НАБОР источников, а не первый из них: после слияния по общему идентификатору у
    # записи их бывает два, и фильтр «по источнику» обязан это показывать честно —
    # иначе объединённые записи молча выпадали бы из среза (замер: 6 вместо 16)
    sources = ', '.join(sorted(o.get('sources') or [o['source']]))
    hay = ' '.join(str(x).lower() for x in
                   (o['strategy_id'], o['strategy_name'], o['mode'],
                    str(o['lifecycle_state']), str(o.get('promotion_status')),
                    str(o.get('rnd_status')), sources))
    return (
        f'<div class="row" data-id="{_e(o["strategy_id"])}" data-hay="{_e(hay)}" '
        f'data-imode="{_e(o["mode"])}" data-ilife="{_e(str(o["lifecycle_state"]))}" '
        f'data-ipromo="{_e(str(o.get("promotion_status") or "нет"))}" '
        f'data-isource="{_e(sources)}" '
        f'data-iapproval="{_e(o["owner_approval_status"])}">'
        f'<div class="rowhead">{_mode(o["mode"])}'
        f'<span class="badge b-unk">{_e(str(o["lifecycle_state"]))}</span>'
        f'<span class="rowtitle">{_e(_cut(o["strategy_name"], 110))}</span></div>'
        f'<details><summary>режим, метрики, риск, улики</summary><dl class="kv">'
        f'<dt>РЕЖИМ</dt><dd>{_mode(o["mode"])}'
        + (f'<div class="evi">{_e(o["mode_evidence"].get("detail"))}</div>'
           if o.get('mode_evidence') else '') + '</dd>'
        + f'<dt>капитал</dt><dd>{_n(o.get("capital_value"))} '
          f'{_e(o.get("capital_currency") or "")}</dd>'
        + f'<dt>метрики</dt><dd>'
        + (f'<ul>{metrics}</ul>' if metrics else '<span class="note">не измерено</span>')
        + '</dd>'
        + f'<dt>риск</dt><dd>{_n(o.get("risk_classification"))}'
        + (f'<ul>{limits}</ul>' if limits else '') + '</dd>'
        + f'<dt>R&amp;D</dt><dd>{_n(o.get("rnd_status"))} · бэктест '
          f'{_n(o.get("backtest_status"))} · canary {_n(o.get("canary_status"))}</dd>'
        + f'<dt>продвижение</dt><dd>{_n(o.get("promotion_status"))}</dd>'
        + f'<dt>одобрение владельца</dt><dd>{_e(o["owner_approval_status"])}</dd>'
        + (f'<dt>расхождение источников</dt><dd><ul>'
           + ''.join(f'<li>{_e(cf["field"])}: {_e(", ".join(cf["values"]))}'
                     f'<div class="evi">{_e(cf["note"])}</div></li>'
                     for cf in o['conflicting_facts']) + '</ul></dd>'
           if o.get('conflicting_facts') else '')
        + (f'<dt>факты по источникам</dt><dd class="mono">'
           f'{_e(", ".join(sorted(o["facts_by_source"])))}</dd>'
           if o.get('facts_by_source') and len(o.get('sources') or []) > 1 else '')
        + f'<dt>источник</dt><dd class="mono">{_e(", ".join(o.get("sources") or [o["source"]]))}'
          f'<div class="evi">наблюдение: {_e(o.get("observed_at") or "не измерено")}'
          f'</div></dd>'
        + f'</dl><h3>Evidence</h3><ul>{ev}</ul></details></div>')


def _investments(inv, available):
    """Раздел 9: инвестиции и R&D — только чтение существующих улик.

    Director OS не становится инвестиционным движком. Кнопок Approve investment, Promote,
    Allocate, Rebalance, Execute, Change risk и Change rate здесь нет и не подразумевается.
    Режимы REAL / PAPER / SHADOW / FORECAST / R&D никогда не складываются.
    """
    if not inv:
        return ('<h2 id="investments">9. Инвестиции и R&amp;D</h2>'
                '<div class="empty">Снимок инвестиций не приложен к этому комплекту. '
                'Это НЕ значит, что инвестиций нет.</div>')
    c = inv['counts']
    cap = inv['capital_by_mode']
    out = ['<h2 id="investments">9. Инвестиции и R&amp;D</h2>',
           '<p class="note">Раздел только читает существующие источники SPA. Стратегии, '
           'доходность, риск и распределение капитала остаются за ними. Ничего не '
           'вычисляется, ничего не запускается, кнопок действий нет.</p>',
           '<div class="card"><h3>Величины по режимам и типам</h3>',
           '<p class="note">Слово «капитал» одним словом здесь не употребляется: '
           'объявленный стартовый капитал, текущая equity, размещённое и кэш — РАЗНЫЕ '
           'величины, и складывать их нельзя.</p>',
           '<table><thead><tr><th>режим</th><th>величина</th><th>значение</th>'
           '<th>валюта</th><th>поле источника</th><th>снято</th></tr></thead><tbody>']
    for m in inv.get('capital_metrics') or []:
        out.append(f'<tr><td>{_mode(m["mode"])}</td>'
                   f'<td class="mono">{_e(m["metric_type"])}'
                   f'<div class="evi">{_e(m.get("note") or "")}</div></td>'
                   f'<td class="big">{_n(m["value"])}</td>'
                   f'<td>{_n(m.get("currency"))}'
                   f'<div class="evi">{_e(m.get("currency_basis") or "")}</div></td>'
                   f'<td class="mono">{_e(m["source"])}.{_e(m["source_field"])}</td>'
                   f'<td class="mono">{_e(m.get("observed_at") or "не измерено")}</td>'
                   f'</tr>')
    if not (inv.get('capital_metrics') or []):
        out.append('<tr><td colspan="6" class="note">ни одна величина не прочитана</td>'
                   '</tr>')
    out += ['</tbody></table>',
            '<h3>Сводка по режимам</h3><dl class="kv">']
    for mode in inv['mode_vocabulary']:
        value = cap.get(mode)
        out.append(f'<dt>{_mode(mode)}</dt><dd class="big">{_n(value)}</dd>')
    out += ['</dl>',
            f'<p class="note"><b>{_e(inv["real_capital_note"])}</b></p>',
            '<ul>' + ''.join(f'<li>{_e(x.get("kind"))}: {_e(_cut(x.get("detail"), 300))}'
                             f'</li>' for x in inv['capital_evidence']) + '</ul>',
            '<p class="note">Режимы не складываются: бумажный капитал — не реальный, '
            'прогнозная доходность — не заработанная.</p>',
            f'<p class="evi">снимок: {_link("investment_snapshot.json", available)}</p>'
            '</div>']

    g, k = inv['golive'], inv['kill_switch']
    out += ['<h3>Риск и стоп-кран — только чтение</h3><div class="card"><dl class="kv">',
            f'<dt>стоп-кран сработал</dt><dd>{_n(k.get("triggered"))}'
            f'<div class="evi">{_e(k.get("reason") or "")} · '
            f'{_e(k.get("observed_at") or "не измерено")}</div></dd>',
            f'<dt>гейты go-live</dt><dd class="big">{_n(g.get("passed"))} из '
            f'{_n(g.get("total"))}</dd>',
            f'<dt>готовность объявлена</dt><dd>{_n(g.get("ready"))}'
            f'<div class="evi">{_e(g.get("note") or "")}</div></dd>',
            '</dl>']
    limits = (inv.get('risk_limits') or {}).get('allocation_limits') or {}
    params = (inv.get('risk_limits') or {}).get('risk_parameters') or {}
    if limits or params:
        out.append('<table><thead><tr><th>ограничение</th><th>значение</th></tr></thead>'
                   '<tbody>'
                   + ''.join(f'<tr><td class="mono">{_e(kk)}</td><td>{_e(vv)}</td></tr>'
                             for kk, vv in list(limits.items()) + list(params.items()))
                   + '</tbody></table>')
    out.append('<p class="note">Значения показаны как объявлены источником; этот раздел '
               'их не меняет и не может.</p></div>')

    pipeline = inv.get('rnd_pipeline')
    out += ['<h3>R&amp;D: конвейер источника</h3><div class="card">',
            f'<p class="mono">{_e(pipeline or "конвейер не объявлен")}</p>',
            f'<p class="note">Стадии взяты у источника ({_e(inv["lifecycle_source"])}); '
            'собственных стадий этот раздел не придумывает. Прямо распределять капитал '
            'R&amp;D не может, кнопки продвижения здесь нет.</p>',
            '<dl class="kv">'
            + ''.join(f'<dt>{_e(kk)}</dt><dd class="big">{_e(vv)}</dd>'
                      for kk, vv in (inv.get('rnd_stage_counts') or {}).items())
            + '</dl></div>']

    proposals = [o for o in inv['objects'] if o.get('promotion_status')
                 and o['promotion_status'] != 'None']
    out.append(f'<h3>Продвижение: предложения источников ({len(proposals)})</h3>')
    if proposals:
        out.append('<p class="note">Это записи движка продвижения, а НЕ совет Director OS '
                   'и не решение владельца.</p>')
        out += [_inv_card(o) for o in proposals[:10]]
    else:
        out.append('<div class="empty">записей о продвижении нет</div>')

    waiting = [o for o in inv['objects'] if o['owner_approval_status'] == 'WAITING']
    out.append(f'<h3>Ждёт инвестиционного решения ({len(waiting)})</h3>')
    out.append('<div class="empty">явных записей об ожидании инвестиционного решения в '
               'источниках нет; по тексту такие решения не угадываются</div>'
               if not waiting else ''.join(_inv_card(o) for o in waiting[:10]))

    modes = sorted({o['mode'] for o in inv['objects']})
    lifes = sorted({str(o['lifecycle_state']) for o in inv['objects']})
    promos = sorted({str(o.get('promotion_status') or 'нет') for o in inv['objects']})
    srcs = sorted({', '.join(sorted(o.get('sources') or [o['source']]))
                   for o in inv['objects']})
    appr = sorted({o['owner_approval_status'] for o in inv['objects']})
    idn = inv.get('strategy_identity') or {}
    out += ['<h3>Тождество стратегий — измерено</h3><div class="card">',
            f'<p class="note"><b>Записей о стратегиях: '
            f'{_e(str(idn.get("strategy_source_records")))}</b>; доказанных уникальных '
            f'идентификаторов: {_e(str(idn.get("proven_unique_strategy_ids")))}. '
            f'Объединено по общему устойчивому идентификатору: '
            f'{_e(str(idn.get("cross_source_exact_id_matches")))}; совпадений только по '
            f'имени: {_e(str(idn.get("name_only_matches")))} — '
            f'{_e(idn.get("name_only_basis") or "")}</p>',
            f'<p class="note">{_e(idn.get("namespace_note") or "")}</p>',
            f'<p class="note">Авторитет между источниками: '
            f'<span class="mono">{_e(idn.get("authority_between_sources"))}</span> — '
            f'{_e(idn.get("authority_note") or "")}</p>',
            '<table><thead><tr><th>источник</th><th>записей</th><th>поле id</th>'
            '<th>уникальных</th><th>дублей</th></tr></thead><tbody>'
            + ''.join(f'<tr><td class="mono">{_e(k)}</td><td class="big">'
                      f'{v["source_record_count"]}</td>'
                      f'<td class="mono">{_e(v["stable_id_field"])}</td>'
                      f'<td>{v["unique_ids"]}</td><td>{v["duplicate_ids"]}</td></tr>'
                      for k, v in (idn.get('per_source') or {}).items())
            + '</tbody></table></div>',
            f'<h3>Записи о стратегиях ({len(inv["objects"])})</h3>',
            '<div id="investments-scope">',
            _controls('investments-scope',
                      [('imode', 'Режим', modes), ('ilife', 'Состояние', lifes),
                       ('ipromo', 'Продвижение', promos), ('isource', 'Источник', srcs),
                       ('iapproval', 'Одобрение владельца', appr)],
                      [('imode', 'по режиму'), ('ilife', 'по состоянию'),
                       ('isource', 'по источнику')]),
            '<div data-role="list">']
    out += [_inv_card(o) for o in inv['objects']]
    out.append('</div></div>')

    out.append('<details><summary>Источники инвестиций и что каждый может доказать'
               '</summary><table><thead><tr><th>источник</th><th>что представляет</th>'
               '<th>род</th><th>режим</th><th>капитал</th><th>доходность</th><th>риск</th>'
               '<th>продвижение</th><th>одобрение</th><th>снят</th></tr></thead><tbody>')
    yes = lambda v: ('да' if v else ('нет' if v is False else '—'))  # noqa: E731
    for s in inv['sources']:
        out.append(f'<tr><td class="mono">{_e(s["source"])}</td>'
                   f'<td class="note">{_e(s.get("represents") or "—")}</td>'
                   f'<td>{_e(s.get("basis") or "—")}</td>'
                   f'<td>{_mode(s.get("mode"))}'
                   f'<div class="evi">{_e((s.get("mode_evidence") or {}).get("detail")
                                          or "поля режима нет")}</div></td>'
                   f'<td>{yes(s.get("can_prove_capital"))}</td>'
                   f'<td>{yes(s.get("can_prove_performance"))}</td>'
                   f'<td>{yes(s.get("can_prove_risk"))}</td>'
                   f'<td>{yes(s.get("can_prove_promotion"))}</td>'
                   f'<td>{yes(s.get("can_prove_owner_approval"))}</td>'
                   f'<td class="mono">{_e(s.get("observed_at") or "—")}'
                   f'<div class="evi">{_e(_cut(s.get("limit") or "", 130))}</div></td>'
                   f'</tr>')
    out.append('</tbody></table></details>')
    out.append('<h3>Границы этого раздела</h3><ul>'
               + ''.join(f'<li>{_e(x)}</li>' for x in inv['limits']) + '</ul>')
    return ''.join(out)


_GOV_BLOCKS = (
    ('decision', 'Решения владельца и ADR'),
    ('permission', 'Разрешения и границы'),
    ('invariant', 'Инварианты'),
    ('rule', 'Действующие правила'),
    ('recovery', 'Восстановление: описано и проверено'),
    ('backup', 'Резервные копии'),
    ('deployment', 'Доставка и откат'),
    ('security', 'Безопасность и секреты'),
    ('gap', 'Пробелы управления'),
)

_RECOVERY_LABELS = {
    'TESTED': 'ПРОВЕРЕНО пробой',
    'DOCUMENTED_UNTESTED': 'описано, пробы НЕТ',
    'MISSING': 'процедуры нет',
    'NOT_APPLICABLE': 'не относится',
    'UNKNOWN': 'не измерено',
}

_ZONE_SCOPE_LABELS = {
    'ZONE_REQUIRED': 'зона требуется правилом',
    'ZONE_NOT_APPLICABLE': 'зона не требуется: это не действие',
    'ZONE_SCOPE_UNKNOWN': 'область зонирования не установлена',
}


def _gov_card(it):
    ev = ''.join(f'<li>{_e(x.get("kind"))}: {_e(_cut(x.get("detail"), 320))}'
                 + (f'<div class="evi mono">{_e(x.get("where"))}</div>'
                    if x.get('where') else '') + '</li>'
                 for x in (it.get('evidence') or [])[:4])
    rec = ''.join(f'<li>{_e(x.get("kind"))}: {_e(_cut(x.get("detail"), 320))}</li>'
                  for x in (it.get('recovery_evidence') or [])[:4])
    hay = ' '.join(str(x).lower() for x in
                   (it['governance_id'], it['title'], it['category'], it['status'],
                    it['permission_zone'], it['recovery_status'], str(it['owner'])))
    return (
        f'<div class="row" data-id="{_e(it["governance_id"])}" data-hay="{_e(hay)}" '
        f'data-gcat="{_e(it["category"])}" data-gzone="{_e(it["permission_zone"])}" '
        f'data-grec="{_e(it["recovery_status"])}" data-gauth="{_e(it["authority_source"])}" '
        f'data-gowner="{_e(str(it["owner"]))}" data-gappr="{_e(it["approval_required"])}" '
        f'data-gclass="{_e(it.get("permission_class") or "UNKNOWN")}" '
        f'data-gscope="{_e(it.get("zone_scope") or "ZONE_SCOPE_UNKNOWN")}">'
        f'<div class="rowhead">'
        f'<span class="badge b-unk">{_e(it["category"])}</span>'
        + ('<span class="badge b-warn">нужно одобрение владельца</span>'
           if it['approval_required'] == 'REQUIRED' else '')
        + (f'<span class="badge b-warn">'
           f'{_e(_RECOVERY_LABELS[it["recovery_status"]])}</span>'
           if it['recovery_status'] == 'DOCUMENTED_UNTESTED' else '')
        + f'<span class="rowtitle">{_e(_cut(it["title"], 130))}</span></div>'
        f'<details><summary>чем управляет, чем доказано</summary><dl class="kv">'
        f'<dt>статус</dt><dd>{_e(it["status"])}</dd>'
        f'<dt>авторитет</dt><dd>{_e(it["authority_source"])}</dd>'
        f'<dt>владелец</dt><dd>{_n(it["owner"] if it["owner"] != "UNKNOWN" else None)}</dd>'
        f'<dt>зона разрешения</dt><dd>{_e(it["permission_zone"])}'
        f'<div class="evi">{_e(_ZONE_SCOPE_LABELS.get(it.get("zone_scope"), ""))}</div>'
        '</dd>'
        f'<dt>род правила</dt><dd>{_e(it.get("permission_class"))}</dd>'
        f'<dt>нужно одобрение</dt><dd>{_e(it["approval_required"])}</dd>'
        f'<dt>восстановление</dt><dd>{_e(_RECOVERY_LABELS[it["recovery_status"]])}'
        + (f'<ul>{rec}</ul>' if rec else '') + '</dd>'
        + f'<dt>безопасность</dt><dd>{_e(it["security_status"])}</dd>'
        + f'<dt>проверено</dt><dd class="mono">{_n(it.get("last_verified_at"))}</dd>'
        + (f'<dt>решение</dt><dd class="mono">{_e(it["decision_ref"])}</dd>'
           if it.get('decision_ref') else '')
        + f'</dl><h3>Evidence</h3><ul>{ev}</ul></details></div>')


def _governance(gov, available):
    """Раздел 10: чем система управляется и можем ли мы её восстановить.

    Кнопок Approve, Rollback, Restore, Rotate secret, Change permission, Change
    RiskPolicy, Trigger kill-switch, Deploy, Delete и Repair здесь нет и не
    подразумевается. Общего балла управления нет намеренно.
    """
    if not gov:
        return ('<h2 id="governance">10. Управление и восстановление</h2>'
                '<div class="empty">Снимок управления не приложен к этому комплекту. '
                'Это НЕ значит, что управление в порядке.</div>')
    c = gov['counts']
    items = gov['items']
    out = ['<h2 id="governance">10. Управление и восстановление</h2>',
           '<p class="note">Какие решения, правила и разрешения управляют системой и чем '
           'доказана наша способность её восстановить. Раздел только читает: ничего не '
           'одобряет, не откатывает, не восстанавливает и не меняет разрешений.</p>',
           '<div class="card"><dl class="kv">',
           f'<dt>Решений (ADR)</dt><dd class="big">{c["decisions"]}</dd>',
           f'<dt>из них с коллизией номера</dt><dd class="big">'
           f'{c["adr_number_collisions"]}</dd>',
           f'<dt>Действующих правил</dt><dd class="big">{c["rules"]}</dd>',
           f'<dt>Инвариантов</dt><dd class="big">{c["invariants"]}</dd>',
           f'<dt>Правил разрешений</dt><dd class="big">{c["permissions"]}</dd>',
           f'<dt>из них ВОРОТ одобрения владельца</dt><dd class="big">'
           f'{c["approval_required"]}</dd>',
           f'<dt>автономных · аварийных</dt><dd class="big">'
           f'{c["autonomous_rules"]} · {c["emergency_rules"]}</dd>',
           f'<dt>Восстановление ПРОВЕРЕНО пробой</dt><dd class="big">'
           f'{c["recovery_tested"]}</dd>',
           f'<dt>описано, но пробы НЕТ</dt><dd class="big">'
           f'{c["recovery_documented_untested"]}</dd>',
           f'<dt>Зона требуется · объявлена · НЕ объявлена</dt><dd class="big">'
           f'{c["zone_required"]} · {c["zone_defined"]} · '
           f'{c["zone_required_but_missing"]}</dd>',
           f'<dt>Пробелов управления</dt><dd class="big">{c["gaps"]}</dd>',
           '</dl>',
           f'<p class="note">{_e(gov["governance_score_note"])}</p>',
           '<p class="note"><b>Наличие резервной копии не является доказательством '
           'восстановления, а описанная процедура отката — проверенной.</b> Это разные '
           'улики, и вторая из первой здесь не выводится.</p>',
           f'<p class="note">Зона разрешения требуется не всем: {_e(gov["zone_scope_basis"])}'
           f' Поэтому записей вне области ({c["zone_not_applicable"]}) пробелом не '
           'считаем.</p>',
           f'<p class="evi">снимок: {_link("governance_snapshot.json", available)}</p>'
           '</div>']

    for category, title in _GOV_BLOCKS:
        rows = [i for i in items if i['category'] == category]
        out.append(f'<h3>{_e(title)} ({len(rows)})</h3>')
        if not rows:
            out.append('<div class="empty">записей нет</div>')
            continue
        out += [_gov_card(i) for i in rows[:8]]
        if len(rows) > 8:
            out.append(f'<p class="note">показаны первые 8 из {len(rows)}; остальные — '
                       'в полном списке ниже с теми же фильтрами</p>')

    cats = sorted({i['category'] for i in items})
    zones = sorted({i['permission_zone'] for i in items})
    recs = sorted({i['recovery_status'] for i in items})
    auths = sorted({i['authority_source'] for i in items})
    owners = sorted({str(i['owner']) for i in items})
    apprs = sorted({i['approval_required'] for i in items})
    classes = sorted({i.get('permission_class') or 'UNKNOWN' for i in items})
    scopes = sorted({i.get('zone_scope') or 'ZONE_SCOPE_UNKNOWN' for i in items})
    out += [f'<h3>Все записи управления ({len(items)})</h3>',
            '<div id="governance-scope">',
            _controls('governance-scope',
                      [('gcat', 'Категория', cats), ('gzone', 'Зона разрешения', zones),
                       ('gclass', 'Род правила', classes),
                       ('gscope', 'Область зонирования', scopes),
                       ('grec', 'Восстановление', recs), ('gauth', 'Авторитет', auths),
                       ('gowner', 'Владелец', owners),
                       ('gappr', 'Нужно одобрение', apprs)],
                      [('gcat', 'по категории'), ('grec', 'по восстановлению'),
                       ('gzone', 'по зоне')]),
            '<div data-role="list">']
    out += [_gov_card(i) for i in items]
    out.append('</div></div>')

    out.append('<details><summary>Источники управления и что каждый из них решает'
               '</summary><table><thead><tr><th>источник</th><th>чем управляет</th>'
               '<th>род</th><th>авторитет</th><th>владелец</th><th>есть процедура '
               'восстановления</th><th>обновлён</th></tr></thead><tbody>')
    yes = lambda v: ('да' if v else ('нет' if v is False else '—'))  # noqa: E731
    for s in gov['sources']:
        out.append(f'<tr><td class="mono">{_e(s["source"])}</td>'
                   f'<td class="note">{_e(s.get("governs") or "—")}</td>'
                   f'<td>{_e(s.get("basis") or "—")}</td>'
                   f'<td><span class="badge b-unk">{_e(s.get("authority_status"))}</span>'
                   f'<div class="evi">'
                   f'{_e(_cut(s.get("authority_quote") or "", 220))}</div></td>'
                   f'<td>{_e(s.get("owner"))}</td>'
                   f'<td>{yes(s.get("has_recovery_procedure"))}</td>'
                   f'<td class="mono">{_e(s.get("last_updated") or "—")}</td></tr>')
    out.append('</tbody></table></details>')
    out.append('<h3>Границы этого раздела</h3><ul>'
               + ''.join(f'<li>{_e(x)}</li>' for x in gov['limits']) + '</ul>')
    return ''.join(out)


def _actions(audit, available):
    """Раздел 11: что Director OS вправе дать нажать — и почему пока ничего.

    Кнопок здесь нет по результату измерения, а не по умолчанию: ни одно существующее
    действие не имеет всех обязательных свойств. Раздел показывает, чего именно не
    хватает, и перечисляет красную зону списком.
    """
    if not audit:
        return ('<h2 id="actions">11. Действия и границы</h2>'
                '<div class="empty">Аудит действий не приложен к этому комплекту. Это НЕ '
                'значит, что действия разрешены.</div>')
    c = audit['counts']
    ready = [a for a in audit['actions'] if a['verdict'] == 'READY_FOR_UI']
    notready = [a for a in audit['actions'] if a['verdict'] == 'NOT_READY_FOR_UI']
    red = [a for a in audit['actions'] if a['verdict'] == 'RED_ZONE']
    out = ['<h2 id="actions">11. Действия и границы</h2>',
           '<p class="note">Director OS не заводит собственный исполнитель. Действие '
           'попадает сюда только если у существующего контура есть ВСЕ обязательные '
           'свойства: канонический исполнитель, зона разрешения, проверка входа, запись в '
           'аудит, поведение при отказе, идемпотентность и откат.</p>',
           '<div class="card"><dl class="kv">',
           f'<dt>ГОТОВЫ для кнопки</dt><dd class="big">{c["ready_for_ui"]}</dd>',
           f'<dt>Не готовы</dt><dd class="big">{c["not_ready"]}</dd>',
           f'<dt>Красная зона</dt><dd class="big">{c["red_zone"]}</dd>',
           '</dl>',
           ('<p class="note"><b>Готовых действий ноль — и это измеренный результат, а не '
            'умолчание.</b> Director OS v1 выходит полностью read-only: ни одной кнопки '
            'действия на портале нет.</p>' if not ready else
            '<p class="note">Каждая кнопка вызывает существующий канонический исполнитель '
            'и перечитывает состояние после выполнения.</p>'),
           f'<p class="evi">аудит: {_link("action_authority_audit.json", available)}</p>'
           '</div>']

    out.append(f'<h3>Чего не хватает кандидатам ({len(notready)})</h3>'
               '<table><thead><tr><th>действие</th><th>канонический исполнитель</th>'
               '<th>не хватает</th><th>кем используется</th></tr></thead><tbody>')
    for a in notready:
        out.append(f'<tr><td>{_e(a["title"])}<div class="evi mono">{_e(a["action"])}</div>'
                   f'</td>'
                   f'<td class="mono">{_e(a["canonical_executor"] or "—")}</td>'
                   f'<td class="note">{_e(", ".join(a["missing_properties"]))}</td>'
                   f'<td class="note">{_e(a["currently_used_by"] or "—")}</td></tr>')
    out.append('</tbody></table>')
    out.append('<table><thead><tr><th>свойство</th><th>что это значит</th>'
               '<th>скольким кандидатам не хватает</th></tr></thead><tbody>'
               + ''.join(f'<tr><td class="mono">{_e(k)}</td>'
                         f'<td class="note">{_e(v)}</td>'
                         f'<td class="big">{c["by_missing_property"].get(k, 0)}</td></tr>'
                         for k, v in audit['property_definitions'].items())
               + '</tbody></table>')

    out.append(f'<h3>Красная зона v1 ({len(red)})</h3>'
               '<p class="note">Эти действия не попадают в интерфейс ни при каких '
               'свойствах. Отдельная будущая архитектура — отдельное решение '
               'владельца.</p><ul>'
               + ''.join(f'<li>{_e(a["title"])} <span class="mono evi">{_e(a["action"])}'
                         f'</span></li>' for a in red) + '</ul>')
    out.append('<h3>Границы этого раздела</h3><ul>'
               + ''.join(f'<li>{_e(x)}</li>' for x in audit['limits']) + '</ul>')
    return ''.join(out)


# ── многостраничная статика: те же снимки, шесть лёгких страниц ──────────────
#
# Монолит на 8,84 МБ и 143 тысячи узлов открывался с телефона плохо, и это было
# ИЗМЕРЕНО, а не предположено. Разделы не переписаны и не урезаны: они те же функции,
# просто разложены по страницам, которые лежат в одном каталоге рядом с уликами.
# Ни SPA, ни сервера, ни базы: шесть обычных файлов, открываются и с file://,
# и с localhost.

PAGES = (
    ('index.html', 'Центр директора', ('director',)),
    ('system.html', 'Система', ('overview', 'agents', 'sources', 'authority')),
    ('reliability.html', 'Надёжность', ('reliability',)),
    ('work.html', 'Работа', ('tasks', 'decisions', 'work')),
    ('investments.html', 'Инвестиции', ('investments',)),
    ('governance.html', 'Управление', ('governance', 'actions')),
)

PAGE_FILES = tuple(name for name, _, _ in PAGES)

_SECTION_PAGE = {section: name for name, _, sections in PAGES for section in sections}


def section_href(anchor):
    """Ссылка на раздел с ЛЮБОЙ страницы: файл рядом плюс якорь.

    Полная форма `work.html#work` работает и внутри той же страницы, и с соседней, и при
    открытии по file://. Голый `#work` работал бы только на одной странице — и именно так
    ссылки «показать все» молча ломались бы после разделения.
    """
    page = _SECTION_PAGE.get(anchor)
    return f'{page}#{anchor}' if page else f'#{anchor}'


def _page_nav(current):
    return ''.join(
        (f'<a href="{_e(name)}" aria-current="page"><b>{_e(title)}</b></a>'
         if name == current else f'<a href="{_e(name)}">{_e(title)}</a>')
        for name, title, _ in PAGES)


def _shell(title, current, design_reference, body):
    design_note = (f'<p class="note">Дизайн-референс: '
                   f'<span class="badge b-unk">{_e(design_reference["state"])}</span> '
                   f'{_e(design_reference["note"])}</p>')
    return '\n'.join([
        '<!DOCTYPE html>', '<html lang="ru">', '<head>', '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="referrer" content="no-referrer">',
        f'<title>{_e(title)} — Earn DeFi Studio OS</title>',
        f'<style>{_CSS}</style>', '</head>', '<body>',
        f'<nav aria-label="страницы портала">{_page_nav(current)}</nav>',
        '<div class="wrap">', f'<h1>{_e(title)}</h1>',
        '<p class="sub">Earn DeFi Studio OS · READ-ONLY · собрано '
        f'{_e(_PAGE_STAMP[0])}</p>', design_note,
        '<div class="card"><span class="note">Портал ничего не запускает, не назначает и '
        'не закрывает: он только показывает уже существующие записи и наблюдения, с путём '
        'к источнику у каждого объекта. Кнопок действий здесь нет намеренно — '
        'неработающая кнопка хуже отсутствующей.</span></div>',
        body, '</div>', f'<script>{_JS}</script>', '</body>', '</html>'])


#: момент сборки страницы. Объявлен волатильным в run_manifest и нигде больше не влияет.
_PAGE_STAMP = ['']


def pages(portal, brief, design_reference, available_evidence=(), authority=None,
          reliability=None, work=None, director=None, investments=None,
          governance=None, actions=None):
    """{имя файла: html}. Логика извлечения не дублируется: разделы те же функции."""
    available = set(available_evidence) | {'portal_snapshot.json', 'run_manifest.json',
                                           'owner_summary.md'}
    available |= set(PAGE_FILES)
    _PAGE_STAMP[0] = portal.get('page_generated_at') or ''
    builders = {
        'director': lambda: _director(director),
        'overview': lambda: _overview(brief, available),
        'tasks': lambda: _tasks(portal),
        'agents': lambda: _agents(portal),
        'decisions': lambda: _decisions(portal, brief),
        'sources': lambda: _sources(portal, brief, available),
        'authority': lambda: _authority(authority, available),
        'reliability': lambda: _reliability(reliability, available),
        'work': lambda: _work_view(work, available),
        'investments': lambda: _investments(investments, available),
        'governance': lambda: _governance(governance, available),
        'actions': lambda: _actions(actions, available),
    }
    out = {}
    for name, title, sections in PAGES:
        body = ''.join(builders[section]() for section in sections)
        out[name] = _shell(title, name, design_reference, body)
    return out


def html(portal, brief, design_reference, available_evidence=(), authority=None,
         reliability=None, work=None, director=None, investments=None,
         governance=None, actions=None):
    available = set(available_evidence) | {'portal_snapshot.json', 'run_manifest.json',
                                           'owner_summary.md', 'index.html'}
    nav = ''.join(f'<a href="#{anchor}">{_e(label)}</a>' for anchor, label in (
        ('director', '0. Центр'), ('overview', '1. Обзор'), ('tasks', '2. Задачи'), ('agents', '3. Агенты и роли'),
        ('decisions', '4. Решения'), ('sources', '5. Источники'),
        ('authority', '6. Источник правды'),
        ('reliability', '7. Надёжность'), ('work', '8. Работа'),
        ('investments', '9. Инвестиции'), ('governance', '10. Управление'),
        ('actions', '11. Действия')))
    design_note = (f'<p class="note">Дизайн-референс: '
                   f'<span class="badge b-unk">{_e(design_reference["state"])}</span> '
                   f'{_e(design_reference["note"])}</p>')
    return '\n'.join([
        '<!DOCTYPE html>', '<html lang="ru">', '<head>', '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="referrer" content="no-referrer">',
        '<title>Портал студии — Earn DeFi Studio OS</title>',
        f'<style>{_CSS}</style>', '</head>', '<body>',
        f'<nav aria-label="разделы портала">{nav}</nav>', '<div class="wrap">',
        '<h1>Портал студии</h1>',
        f'<p class="sub">Earn DeFi Studio OS · READ-ONLY · собрано '
        f'{_e(portal.get("page_generated_at"))}</p>',
        design_note,
        '<div class="card"><span class="note">Портал ничего не запускает, не назначает и '
        'не закрывает: в этой фазе он только показывает уже существующие записи и '
        'наблюдения, с путём к источнику у каждого объекта. Кнопок действий здесь нет '
        'намеренно — неработающая кнопка хуже отсутствующей.</span></div>',
        _director(director),
        _overview(brief, available), _tasks(portal), _agents(portal),
        _decisions(portal, brief), _sources(portal, brief, available),
        _authority(authority, available),
        _reliability(reliability, available),
        _work_view(work, available),
        _investments(investments, available),
        _governance(governance, available),
        _actions(actions, available),
        '</div>', f'<script>{_JS}</script>', '</body>', '</html>'])


def owner_summary(portal, brief, design_reference):
    c = portal['counts']
    L = ['# Портал студии — короткая сводка', '',
         f'Собрано: {portal.get("page_generated_at")} · READ-ONLY.',
         f'Дизайн-референс: **{design_reference["state"]}** — {design_reference["note"]}', '',
         '| | |', '|---|---|',
         f'| Задачи | {c["tasks"]} ({", ".join(f"{k}: {v}" for k, v in sorted(c["by_tracker"].items()))}) |',
         f'| Записанные решения владельца | {c["owner_decision_records"]} |',
         f'| Агенты и роли | {c["agents_and_roles"]} |',
         f'| Доказуемых связей | {c["provable_links"]} |',
         f'| Строк-заявок исполнителя (не метки агентов) | {c["executor_claims"]} |',
         f'| Расхождений источников | {c["conflicts"]} |',
         f'| Ошибок извлечения | {c["extraction_errors"]} |',
         f'| Закрытых inbox без подтверждённой приёмки | {c["closed_inbox_without_confirmed_acceptance"]} |',
         f'| Закрытых записей вне правила приёмки | {c["closed_records_outside_the_acceptance_rule"]} |',
         '']
    if brief:
        f = brief['freshness_and_coverage']
        L += [f'Наблюдение машины снято {f["observed_at"]} (возраст на момент сборки '
              f'сводки — {f["age_at_generation_human"]}, порог {f["freshness_policy"]}).',
              f'Подтверждённых изменений: {brief["counts"]["confirmed_changes"]} · '
              f'внимание: {brief["counts"]["attention_items"]} · '
              f'кандидатов решений: {brief["counts"]["owner_candidates"]}.', '']
    L += ['## Что портал НЕ утверждает', '']
    L += [f'- {x}' for x in portal['limits']]
    L += ['', 'Полные данные: `portal_snapshot.json`. Страница: `index.html`.', '']
    return '\n'.join(L)
