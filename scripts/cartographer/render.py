#!/usr/bin/env python3
"""Presentation for the Owner Briefing: Markdown and one static HTML file.

Both renderers read the SAME briefing structure and add no fact of their own — a line
that appears in the page must be present in `owner_briefing.json`.

The page is deliberately plain: one file, inline styles, no CDN, no external font, no
analytics, no network request of any kind, and no control that could run anything. It
opens from disk with a double click and is readable on a phone.

Offline by construction: no ``subprocess``, no ``socket``, no ``urllib``.
"""
import html as _html
import json

STATE_WORDS = {True: 'доступен', False: 'НЕДОСТУПЕН', None: 'UNKNOWN'}


def _e(value):
    """Escape anything for HTML. Never trust a path, a reason or an id."""
    if value is None:
        return '—'
    if isinstance(value, bool):
        return 'да' if value else 'нет'
    return _html.escape(str(value), quote=True)


def _short(value, limit=120):
    text = '—' if value is None else str(value)
    return text if len(text) <= limit else text[:limit - 1] + '…'


# ── Markdown ─────────────────────────────────────────────────────────────────

def markdown(b):
    f = b['freshness_and_coverage']
    ch, counts = b['material_changes'], b['counts']
    L = ['# Сводка для владельца — Earn DeFi Studio OS', '',
         f"Режим: **{'сравнение' if b['mode'] == 'comparison' else 'первый запуск'}** — {b['mode_note']}", '',
         '| | |', '|---|---|',
         f"| Наблюдение снято | {f['observed_at']} |",
         f"| Возраст наблюдения на момент сборки | {f['age_at_generation_human']} "
         f"(порог: {f['freshness_policy']}) |",
         f"| Страница собрана | {b['generated_at']} |",
         f"| Окно наблюдения | {f['capture_window']['duration_seconds']} с, не атомарно |",
         f"| Отпечаток содержания | `{b['semantic_digest'][:16]}…` |", '',
         f"**{f['stale_summary_is_not_a_broken_system']}**", '',
         '## 1. На какой момент у нас достоверная картина', '',
         '| Источник | Состояние | Если недоступен |', '|---|---|---|']
    for s in f['sources']:
        L.append(f"| {s['source']} | **{s['state']}** | {s['if_unavailable']} |")
    L += ['', '**Git baseline сравнения:**']
    for g in f['git_baselines']:
        moved = {True: ' — **сдвинулся между прогонами**', False: '', None: ''}[
            g['baseline_changed_between_the_two_runs']]
        L.append(f"- `{g['repository']}` → `{str(g['reference_sha'])[:12]}` "
                 f"({g['basis']}){moved}")
    L += ['', '**Не измеряется вовсе:**'] + [f'- {x}' for x in f['not_measured']]

    L += ['', '## 2. Что существенно изменилось', '']
    if b['mode'] == 'first_run':
        L.append('Прошлое наблюдение не выбрано — сравнения нет и оно не выдумывается.')
    elif counts['confirmed_changes'] == 0:
        L.append('**Подтверждённых существенных изменений нет.** Это корректный результат, '
                 'а не пустая страница: ниже видно, что именно проверялось.')
    else:
        for item in ch['confirmed']:
            L.append(f"- **{item['headline']}** — `{item['subject']}`"
                     + (f" · {item['detail']}" if item['detail'] else '')
                     + f": {_short(item['old'], 60)} → {_short(item['new'], 60)}")
            if item['note']:
                L.append(f"  - _{item['note']}_")
    for key, title in (('observation_quality', 'Изменилось качество наблюдения'),
                       ('applicability', 'Изменилась применимость правил'),
                       ('informational', 'Информационные переходы')):
        if ch[key]:
            L += ['', f'**{title}: {len(ch[key])}**']
            for item in ch[key][:5]:
                L.append(f"- {item['headline']} — `{item['subject']}`")
            if len(ch[key]) > 5:
                L.append(f'- … ещё {len(ch[key]) - 5}, полный список в `owner_briefing.json`')
    L += ['', '_Семантика сравнения:_ ' + ' '.join(b['semantic_guards'])]

    L += ['', '## 3. Что требует внимания', '']
    if not b['attention']:
        L.append('Ни одно наблюдение не подпадает под записанные основания для внимания.')
    for a in b['attention']:
        L += [f"### {a['headline']} — {a['count']}", '',
              f"{a['practical_meaning']}", '',
              f"Критичность: **{a['severity']}** ({a['severity_note']}).",
              f"Правило: `{a['rule_code']}`. Примеры: "
              + ', '.join(f"`{x['label']}`" for x in a['examples']) + '.', '']

    L += ['## 4. Что может потребовать решения владельца', '']
    if not b['owner_decision_candidates']:
        L.append('Ни одно существующее писаное правило не ставит наблюдаемое на стол '
                 'владельца.')
    for c in b['owner_decision_candidates']:
        L += [f"### `{c['id']}`", '',
              f"- наблюдаемый факт: {c['observed_fact']}",
              f"- почему может понадобиться решение: {c['why_a_decision_may_be_needed']}",
              f"- существующее правило: {c['existing_rule']}",
              f"- что ещё нужно выяснить: {c['what_must_still_be_found_out']}",
              f"- возможный безопасный шаг: {c['possible_next_safe_step']}",
              f"- критичность: {c['severity']} · срок: {c['deadline']} · {c['obligation']}",
              f"- сделано: {c['action_taken']}", '']

    L += ['## 5. Чего система пока не знает', '']
    for u in b['unknowns']:
        tag = ' (по построению)' if u['is_by_design'] else ''
        L.append(f"- **{u['rule_code']}** — {u['count']}{tag}: {u['headline']}")
    if not b['unknowns']:
        L.append('- Неизвестных, зафиксированных снимком, нет.')

    L += ['', '## 6. Чего эта сводка НЕ доказывает', '']
    L += [f'- {x}' for x in b['claim_limits']]
    L += ['', f"_Сводная оценка здоровья: **отсутствует**. {b['overall_health_note']}_", '',
          'Полные данные и ссылки на evidence — `owner_briefing.json`; изменения — '
          '`diff.json`; источники — `source_of_truth.json`; входы и хеши — '
          '`run_manifest.json`.', '']
    return '\n'.join(L) + '\n'


# ── HTML ─────────────────────────────────────────────────────────────────────

_CSS = """
:root{--bg:#fbfbf9;--fg:#1d1d1b;--mut:#5d5d57;--line:#dedcd4;--card:#fff;
--warn:#8a5a00;--warnbg:#fdf4e3;--unk:#41506b;--unkbg:#eef1f6;--ok:#2f5d3a;--okbg:#eef5ef}
@media (prefers-color-scheme:dark){:root{--bg:#16161a;--fg:#ececea;--mut:#a3a39c;
--line:#30302f;--card:#1e1e22;--warn:#e8b562;--warnbg:#2a2318;--unk:#a8bade;--unkbg:#1b2130;
--ok:#8bc79a;--okbg:#18231b}}
*{box-sizing:border-box}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);
font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
-webkit-text-size-adjust:100%}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:1.45rem;margin:.2em 0 .1em}
h2{font-size:1.15rem;margin:1.6em 0 .4em;padding-top:.6em;border-top:1px solid var(--line)}
h3{font-size:1rem;margin:1.1em 0 .3em}
p,li{margin:.4em 0}
.sub{color:var(--mut);font-size:.9rem;margin-bottom:1em}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:12px 14px;margin:.7em 0}
.kv{display:grid;grid-template-columns:minmax(9rem,auto) 1fr;gap:.25em .8em;font-size:.94rem}
.kv dt{color:var(--mut)}
.kv dd{margin:0;overflow-wrap:anywhere}
.badge{display:inline-block;padding:.08em .5em;border-radius:6px;font-size:.8rem;
font-weight:600;border:1px solid currentColor;white-space:nowrap}
.b-ok{color:var(--ok);background:var(--okbg)}
.b-warn{color:var(--warn);background:var(--warnbg)}
.b-unk{color:var(--unk);background:var(--unkbg)}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.86em;
overflow-wrap:anywhere;word-break:break-word}
table{border-collapse:collapse;width:100%;font-size:.9rem;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:.4em .55em;text-align:left;vertical-align:top}
th{background:var(--unkbg);color:var(--fg)}
details{margin:.5em 0}
summary{cursor:pointer;color:var(--mut);font-size:.9rem}
ul{padding-left:1.2em}
.big{font-size:1.05rem;font-weight:600}
.note{color:var(--mut);font-size:.88rem}
.evi{color:var(--mut);font-size:.8rem;overflow-wrap:anywhere}
.toc a{color:inherit}
@media (max-width:520px){body{padding:12px 10px}h1{font-size:1.25rem}
.kv{grid-template-columns:1fr}.kv dt{margin-top:.4em}}
"""


def _badge(state):
    cls = {'доступен': 'b-ok', 'НЕДОСТУПЕН': 'b-warn'}.get(state, 'b-unk')
    return f'<span class="badge {cls}">{_e(state)}</span>'


def _evi(item):
    ev = item.get('evidence') or {}
    if not ev:
        return ''
    note = f" — {_e(ev.get('note'))}" if ev.get('note') else ''
    return (f'<div class="evi">evidence: <code>{_e(ev.get("artifact"))}</code> → '
            f'<code>{_e(ev.get("pointer"))}</code>{note}</div>')


def html(b):
    f = b['freshness_and_coverage']
    ch, counts = b['material_changes'], b['counts']
    mode_word = 'сравнение двух наблюдений' if b['mode'] == 'comparison' else 'первый запуск'
    P = ['<!DOCTYPE html>', '<html lang="ru">', '<head>', '<meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         '<meta name="referrer" content="no-referrer">',
         '<title>Сводка для владельца — Earn DeFi Studio OS</title>',
         f'<style>{_CSS}</style>', '</head>', '<body><div class="wrap">',
         '<h1>Сводка для владельца</h1>',
         f'<div class="sub">Earn DeFi Studio OS · режим: <strong>{_e(mode_word)}</strong> · '
         f'страница собрана {_e(b["generated_at"])}</div>']

    # --- шапка: главное сразу
    P += ['<div class="card"><dl class="kv">',
          f'<dt>Наблюдение снято</dt><dd class="mono">{_e(f["observed_at"])}</dd>',
          f'<dt>Возраст наблюдения</dt><dd>{_e(f["age_at_generation_human"])} '
          f'<span class="badge b-unk">порог: {_e(f["freshness_policy"])}</span></dd>',
          f'<dt>Подтверждённых изменений</dt><dd class="big">{counts["confirmed_changes"]}</dd>',
          f'<dt>Требует внимания</dt><dd class="big">{counts["attention_items"]} '
          f'основани{"й" if counts["attention_items"] != 1 else "е"}</dd>',
          f'<dt>Кандидатов на решение владельца</dt><dd class="big">{counts["owner_candidates"]}</dd>',
          f'<dt>Неизвестного</dt><dd class="big">{counts["unknown_findings"]} '
          f'в {counts["unknown_groups"]} группах</dd>',
          f'<dt>Общая оценка здоровья</dt><dd><span class="badge b-unk">не выводится</span></dd>',
          '</dl>',
          f'<p class="note">{_e(b["overall_health_note"])}</p>',
          f'<p class="note">{_e(f["stale_summary_is_not_a_broken_system"])}</p>',
          '</div>']

    # --- 1. актуальность и покрытие
    P += ['<h2>1. На какой момент у нас достоверная картина</h2>',
          f'<p class="note">Окно наблюдения: {_e(f["capture_window"]["started_at"])} → '
          f'{_e(f["capture_window"]["finished_at"])} '
          f'({_e(f["capture_window"]["duration_seconds"])} с, не атомарно). '
          f'{_e(f["freshness_note"])}</p>',
          '<table><thead><tr><th>Источник</th><th>Состояние</th>'
          '<th>Если недоступен</th></tr></thead><tbody>']
    for s in f['sources']:
        P.append(f'<tr><td>{_e(s["source"])}</td><td>{_badge(s["state"])}</td>'
                 f'<td class="note">{_e(s["if_unavailable"])}</td></tr>')
    P.append('</tbody></table>')
    P.append('<h3>Git baseline сравнения</h3><ul>')
    for g in f['git_baselines']:
        moved = ''
        if g['baseline_changed_between_the_two_runs']:
            moved = ' <span class="badge b-warn">линейка сдвинулась между прогонами</span>'
        P.append(f'<li><code>{_e(g["repository"])}</code> → '
                 f'<code>{_e(str(g["reference_sha"])[:12])}</code> '
                 f'<span class="note">({_e(g["basis"])})</span>{moved}{_evi(g)}</li>')
    P.append('</ul>')
    P.append('<details><summary>Что не измеряется вовсе</summary><ul>'
             + ''.join(f'<li>{_e(x)}</li>' for x in f['not_measured']) + '</ul></details>')

    # --- 2. изменения
    P += ['<h2>2. Что существенно изменилось</h2>']
    if b['mode'] == 'first_run':
        P.append('<div class="card"><p class="big">Прошлое наблюдение не выбрано.</p>'
                 '<p class="note">Сравнение не выдумывается: показано только текущее '
                 'состояние.</p></div>')
    elif counts['confirmed_changes'] == 0:
        P.append('<div class="card"><p class="big">Подтверждённых существенных изменений '
                 'нет.</p><p class="note">Это корректный результат, а не пустая страница: '
                 'ниже видно, что именно проверялось и что осталось неизвестным.</p></div>')
    else:
        for item in ch['confirmed']:
            P.append('<div class="card">'
                     f'<div class="big">{_e(item["headline"])}</div>'
                     f'<div class="mono">{_e(item["subject"])}'
                     + (f' · {_e(item["detail"])}' if item['detail'] else '') + '</div>'
                     f'<div>{_e(_short(item["old"], 200))} → '
                     f'<strong>{_e(_short(item["new"], 200))}</strong></div>'
                     + (f'<p class="note">{_e(item["note"])}</p>' if item['note'] else '')
                     + _evi(item) + '</div>')
    for key, title in (('observation_quality', 'Изменилось качество наблюдения'),
                       ('applicability', 'Изменилась применимость правил'),
                       ('informational', 'Информационные переходы')):
        if ch[key]:
            rows = ''.join(
                f'<li>{_e(i["headline"])} — <code>{_e(i["subject"])}</code>'
                + (f' · <code>{_e(i["detail"])}</code>' if i['detail'] else '')
                + (f'<div class="note">{_e(i["note"])}</div>' if i.get('note') else '')
                + '</li>' for i in ch[key])
            P.append(f'<details><summary>{_e(title)}: {len(ch[key])}</summary>'
                     f'<ul>{rows}</ul></details>')
    P.append('<details><summary>Семантика сравнения (что именно не подменяется)</summary><ul>'
             + ''.join(f'<li>{_e(x)}</li>' for x in b['semantic_guards']) + '</ul></details>')

    # --- 3. внимание
    P += ['<h2>3. Что требует внимания</h2>']
    if not b['attention']:
        P.append('<div class="card"><p>Ни одно наблюдение не подпадает под записанные '
                 'основания для внимания.</p></div>')
    for a in b['attention']:
        examples = ''.join(
            f'<li><code>{_e(x["label"])}</code>'
            + (f'<div class="evi">в {_e(x["subject"])}</div>'
               if x.get('context') and x.get('subject') != x.get('label') else '')
            + '</li>' for x in a['examples'])
        full = ''.join(f'<li><code>{_e(i)}</code></li>' for i in a['all_finding_ids'])
        since = ''
        if a['since_last_observation']:
            since = (f'<span class="badge b-unk">новых: '
                     f'{a["since_last_observation"]["new_in_this_comparison"]} · '
                     f'перешло: {a["since_last_observation"]["carried_over"]}</span>')
        P.append('<div class="card">'
                 f'<div class="big">{_e(a["headline"])} — {a["count"]}</div>'
                 f'<p>{_e(a["practical_meaning"])}</p>'
                 f'<p class="note">Критичность: <span class="badge b-unk">'
                 f'{_e(a["severity"])}</span> {since}<br>{_e(a["severity_note"])}</p>'
                 f'<ul>{examples}</ul>'
                 f'<details><summary>Все {a["count"]} · правило '
                 f'{_e(a["rule_code"])}</summary><ul>{full}</ul></details>'
                 + _evi(a) + '</div>')

    # --- 4. решения владельца
    P += ['<h2>4. Что может потребовать решения владельца</h2>',
          '<p class="note">Это производные кандидаты, а не журнал решений: здесь ничего не '
          'создаётся, не закрывается и не исполняется.</p>']
    if not b['owner_decision_candidates']:
        P.append('<div class="card"><p>Ни одно существующее писаное правило не ставит '
                 'наблюдаемое на стол владельца.</p></div>')
    for c in b['owner_decision_candidates']:
        ex = ''.join(f'<li><code>{_e(x)}</code></li>' for x in c['examples'])
        P.append('<div class="card">'
                 f'<div class="big"><code>{_e(c["id"])}</code></div>'
                 f'<dl class="kv">'
                 f'<dt>наблюдаемый факт</dt><dd>{_e(c["observed_fact"])}</dd>'
                 f'<dt>почему решение</dt><dd>{_e(c["why_a_decision_may_be_needed"])}</dd>'
                 f'<dt>существующее правило</dt><dd>{_e(c["existing_rule"])}</dd>'
                 f'<dt>что выяснить</dt><dd>{_e(c["what_must_still_be_found_out"])}</dd>'
                 f'<dt>безопасный шаг</dt><dd>{_e(c["possible_next_safe_step"])}</dd>'
                 f'<dt>критичность</dt><dd><span class="badge b-unk">{_e(c["severity"])}</span> '
                 f'· срок: <span class="badge b-unk">{_e(c["deadline"])}</span></dd>'
                 f'<dt>обязательность</dt><dd>{_e(c["obligation"])}</dd>'
                 f'<dt>сделано</dt><dd>{_e(c["action_taken"])}</dd></dl>'
                 f'<details><summary>Примеры наблюдений</summary><ul>{ex}</ul></details>'
                 + _evi(c) + '</div>')

    # --- 5. неизвестное
    P += ['<h2>5. Чего система пока не знает</h2>']
    for u in b['unknowns']:
        by_design = ('<span class="badge b-unk">по построению</span>'
                     if u['is_by_design'] else '')
        subjects = ''.join(f'<li><code>{_e(x)}</code></li>' for x in u['subjects'][:200])
        details = ''
        if u.get('details'):
            details = '<ul>' + ''.join(
                f'<li><code>{_e(x["id"])}</code>: {_e(x.get("why"))}</li>'
                for x in u['details']) + '</ul>'
        P.append('<div class="card">'
                 f'<div class="big">{_e(u["rule_code"])} — {u["count"]} {by_design}</div>'
                 f'<p class="note">{_e(u["headline"])}</p>'
                 f'<details><summary>Предметы ({len(u["subjects"])})</summary>'
                 f'<ul>{subjects}</ul>{details}</details>' + _evi(u) + '</div>')
    if not b['unknowns']:
        P.append('<div class="card"><p>Неизвестных, зафиксированных снимком, нет.</p></div>')

    # --- 6. границы
    P += ['<h2>6. Чего эта сводка НЕ доказывает</h2><ul>']
    P += [f'<li>{_e(x)}</li>' for x in b['claim_limits']]
    P.append('</ul>')

    prov = b.get('provenance') or {}
    P.append('<details><summary>Происхождение: входы, хеши, версии</summary>'
             f'<pre class="mono">{_e(json.dumps(prov, ensure_ascii=False, indent=2))}</pre>'
             f'<p class="evi">отпечаток содержания сводки: '
             f'<code>{_e(b["semantic_digest"])}</code></p></details>')
    P.append('<p class="note">Страница статическая: ни одной сетевой загрузки, ни одной '
             'кнопки, что-либо запускающей. Все выводы прослеживаются до файлов '
             '<code>owner_briefing.json</code>, <code>diff.json</code>, '
             '<code>source_of_truth.json</code>, <code>run_manifest.json</code> рядом.</p>')
    P += ['</div></body></html>']
    return '\n'.join(P) + '\n'
