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


def html(portal, brief, design_reference, available_evidence=(), authority=None,
         reliability=None):
    available = set(available_evidence) | {'portal_snapshot.json', 'run_manifest.json',
                                           'owner_summary.md', 'index.html'}
    nav = ''.join(f'<a href="#{anchor}">{_e(label)}</a>' for anchor, label in (
        ('overview', '1. Обзор'), ('tasks', '2. Задачи'), ('agents', '3. Агенты и роли'),
        ('decisions', '4. Решения'), ('sources', '5. Источники'),
        ('authority', '6. Источник правды'),
        ('reliability', '7. Надёжность')))
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
        _overview(brief, available), _tasks(portal), _agents(portal),
        _decisions(portal, brief), _sources(portal, brief, available),
        _authority(authority, available),
        _reliability(reliability, available),
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
