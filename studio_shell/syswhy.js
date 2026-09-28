// SYSTEM (Mission-Control-adapted operational panels) + WHY (decision trace).
// SYSTEM panel patterns COPY+ADAPT from builderz-labs/mission-control @ e28edf8b (MIT):
//   src/components/layout/live-feed.tsx (pulsing-dot header + count + timestamped status rows)
//   src/components/dashboard/widgets/fleet-status-widget.tsx (status label + count + dot rows)
//   Adapted to our mono-monochrome design system + real read_model data (not their Tailwind/data).
// WHY trace reuses FounderOS hex/edge idiom (vendor/founderos_layout.js) as a DIRECTED causal graph.
// Read-only. UI ≠ canonical. No fabricated activity; absence shown as NOT MEASURED.
import { hexPts, edgeArc } from './vendor/founderos_layout.js';

const SVGNS = 'http://www.w3.org/2000/svg';
const H = (t, a = {}, ...k) => { const n = document.createElement(t); for (const [key, v] of Object.entries(a)) { if (v == null) continue; if (key === 'class') n.className = v; else if (key.startsWith('on')) n.addEventListener(key.slice(2), v); else n.setAttribute(key, v); } for (const c of k) if (c != null) n.append(c.nodeType ? c : document.createTextNode(c)); return n; };
const S = (t, a = {}, ...k) => { const n = document.createElementNS(SVGNS, t); for (const [key, v] of Object.entries(a)) if (v != null) n.setAttribute(key, v); for (const c of k) if (c != null) n.append(c.nodeType ? c : document.createTextNode(c)); return n; };

const L = {
  ru: { control: 'КОНТРОЛЬ', work: 'РАБОТА', execution: 'ИСПОЛНЕНИЕ', health: 'ЗДОРОВЬЕ', activity: 'АКТИВНОСТЬ',
    live: 'ЖИВАЯ ЛЕНТА', notmsr: 'НЕ ИЗМЕРЕНО', dispatch: 'ДИСПЕТЧ', open: 'ОТКРЫТА', closed: 'ЗАКРЫТА',
    running: 'ВЫПОЛНЯЕТСЯ', queued: 'В ОЧЕРЕДИ', review: 'ПРОВЕРКА', owner_wait: 'ЖДЁТ ВЛАДЕЛЬЦА', blocked: 'ЗАБЛОК.', failed: 'ОШИБКИ', done: 'ГОТОВО',
    provider: 'ПЛОСКОСТЬ PROVIDER', candidate: 'ПЛОСКОСТЬ CANDIDATE', fleet: 'ФЛОТ', golive: 'GO-LIVE', alerts: 'РИСК-АЛЕРТЫ', missions: 'МИССИИ',
    whytitle: 'ПОЧЕМУ', partial: 'ТРАССА НЕПОЛНАЯ', det: 'ДЕТЕРМИНИРОВАННЫЙ ГЕЙТ', llm: 'LLM (без полномочий)', prov: 'ИСТОЧНИК', lastlive: 'посл. активность' },
  en: { control: 'CONTROL', work: 'WORK', execution: 'EXECUTION', health: 'HEALTH', activity: 'ACTIVITY',
    live: 'LIVE FEED', notmsr: 'NOT MEASURED', dispatch: 'DISPATCH', open: 'OPEN', closed: 'CLOSED',
    running: 'RUNNING', queued: 'QUEUED', review: 'REVIEW', owner_wait: 'WAITING FOR OWNER', blocked: 'BLOCKED', failed: 'FAILED', done: 'COMPLETED',
    provider: 'PROVIDER PLANE', candidate: 'CANDIDATE PLANE', fleet: 'FLEET', golive: 'GO-LIVE', alerts: 'RISK ALERTS', missions: 'MISSIONS',
    whytitle: 'WHY', partial: 'TRACE PARTIAL', det: 'DETERMINISTIC GATE', llm: 'LLM (no authority)', prov: 'SOURCE', lastlive: 'last activity' },
};
const STATUS_DOT = { running: '#7aa2d8', owner_wait: '#d6a94a', review: '#5fb8ac', queued: '#6b7690', planned: '#6b7690', blocked: '#d68b5a', failed: '#d66a6a', done: '#5aa17a' };

// ── SYSTEM: MC-adapted operational panels ────────────────────────────────────────────
export function renderSystem(mount, rm, lang) {
  const t = (k) => (L[lang] || L.en)[k] || (L.en[k]) || k;
  mount.replaceChildren();
  const ov = rm.overview || {}, c = ov.counts || {}, sys = rm.system || {};
  const panel = (title, ...rows) => { const p = H('div', { class: 'op-panel' }); p.append(H('div', { class: 'op-head' }, title)); rows.forEach(r => r && p.append(r)); return p; };
  const dot = (col) => H('span', { class: 'op-dot', style: `background:${col}` });
  const statusRow = (label, count, col) => H('div', { class: 'op-row', style: count ? '' : 'opacity:.5' }, dot(col), H('span', { class: 'op-lbl' }, label), H('span', { class: 'op-ct' }, String(count ?? '—')));
  const kv = (k, v, warn) => H('div', { class: 'op-row' }, H('span', { class: 'op-lbl' }, k), H('span', { class: 'op-ct' + (warn ? ' warn' : '') }, v));

  // WORK (fleet-status-widget pattern: status label + count + dot)
  const decCount = (rm.decisions && rm.decisions.items && rm.decisions.items.length) || 0;
  mount.append(panel(t('work'),
    statusRow(t('owner_wait'), (c.owner_wait || 0) + decCount, STATUS_DOT.owner_wait),
    statusRow(t('running'), c.running || 0, STATUS_DOT.running),
    statusRow(t('review'), c.review || 0, STATUS_DOT.review),
    statusRow(t('queued'), c.queued || 0, STATUS_DOT.queued),
    statusRow(t('blocked'), c.blocked || 0, STATUS_DOT.blocked),
    statusRow(t('failed'), c.failed || 0, STATUS_DOT.failed),
    statusRow(t('done'), c.done || 0, STATUS_DOT.done)));

  // EXECUTION (planes + dispatch)
  const disp = sys.dispatch || {};
  mount.append(panel(t('execution'),
    kv(t('dispatch'), disp.open ? t('open') : t('closed'), !disp.open),
    kv(t('provider'), (sys.provider_plane && sys.provider_plane.last_activity && sys.provider_plane.last_activity.freshness) || t('notmsr')),
    kv(t('candidate'), (sys.candidate_plane && sys.candidate_plane.last_activity && sys.candidate_plane.last_activity.freshness) || t('notmsr'))));

  // HEALTH
  const gl = sys.golive, ra = sys.health && sys.health.risk_alerts, fl = rm.roles && rm.roles.fleet;
  mount.append(panel(t('health'),
    gl ? kv(t('golive'), (gl.passed ?? '—') + '/' + (gl.total ?? '—') + (gl.freshness ? ' · ' + gl.freshness.freshness : ''), gl.freshness && gl.freshness.freshness === 'STALE') : null,
    ra ? kv(t('alerts'), String(ra.count ?? t('notmsr')), (ra.count || 0) > 0) : null,
    fl ? kv(t('fleet'), (fl.total_loaded ?? '—') + '/' + (fl.total_known ?? '—') + (fl.freshness ? ' · ' + fl.freshness.freshness : ''), fl.freshness && fl.freshness.freshness === 'STALE') : null));

  // ACTIVITY (live-feed pattern: pulsing dot + count + timestamped rows). No fake activity.
  const acts = rm.activity || [];
  const feed = H('div', { class: 'op-panel op-feed' });
  feed.append(H('div', { class: 'op-head' }, H('span', { class: 'op-pulse' }), t('live'), H('span', { class: 'op-fct' }, String(acts.length))));
  if (!acts.length) feed.append(H('div', { class: 'op-empty' }, t('notmsr')));
  else acts.slice(0, 14).forEach(a => feed.append(H('div', { class: 'op-arow' }, dot(STATUS_DOT[(a.kind === 'transition' && /FAIL/i.test(a.text)) ? 'failed' : 'running'] || '#6b7690'), H('span', { class: 'op-atime' }, shortTs(a.ts, lang)), H('span', { class: 'op-atext' }, a.text))));
  mount.append(feed);
}
function shortTs(s, lang) { if (!s) return '—'; try { return new Date(s).toLocaleTimeString(lang === 'ru' ? 'ru-RU' : 'en-US', { hour: '2-digit', minute: '2-digit' }); } catch { return ''; } }

// ── HOME: command center (5-second answer), MC operational clarity ────────────────────
const HL = {
  ru: { needs: 'ЖДЁТ ВАС', running: 'ВЫПОЛНЯЕТСЯ', blocked: 'ЗАБЛОК.', failed: 'ОШИБКИ', alerts: 'РИСК-АЛЕРТЫ', dispatch: 'ДИСПЕТЧ',
    open: 'ОТКР', closed: 'ЗАКР', ownerq: 'РЕШЕНИЯ ВЛАДЕЛЬЦА', activity: 'ЖИВАЯ ЛЕНТА', health: 'ЗДОРОВЬЕ', work: 'РАБОТА', notmsr: 'НЕ ИЗМЕРЕНО',
    waiting: 'ждёт вашего решения', golive: 'GO-LIVE', fleet: 'ФЛОТ', provider: 'PROVIDER', candidate: 'CANDIDATE', done: 'ГОТОВО', missions: 'МИССИИ', empty: 'Пусто' },
  en: { needs: 'NEEDS YOU', running: 'RUNNING', blocked: 'BLOCKED', failed: 'FAILED', alerts: 'RISK ALERTS', dispatch: 'DISPATCH',
    open: 'OPEN', closed: 'CLOSED', ownerq: 'OWNER DECISIONS', activity: 'LIVE FEED', health: 'HEALTH', work: 'WORK', notmsr: 'NOT MEASURED',
    waiting: 'waiting for your decision', golive: 'GO-LIVE', fleet: 'FLEET', provider: 'PROVIDER', candidate: 'CANDIDATE', done: 'COMPLETED', missions: 'MISSIONS', empty: 'Empty' },
};
export function renderHome(mount, rm, lang) {
  const t = (k) => (HL[lang] || HL.en)[k] || k;
  mount.replaceChildren();
  const wrap = H('div', { class: 'home' });
  const ov = rm.overview || {}, c = ov.counts || {}, sys = rm.system || {};
  const dec = (rm.decisions && rm.decisions.items) || [];
  const disp = sys.dispatch || {};
  const hero = H('div', { class: 'home-hero' });
  const kpi = (l, v, cls) => H('div', { class: 'kpi ' + (cls || '') }, H('div', { class: 'v' }, String(v)), H('div', { class: 'l' }, l));
  hero.append(
    kpi(t('needs'), (c.owner_wait || 0) + dec.length, 'warn'),
    kpi(t('running'), c.running || 0, 'acc'),
    kpi(t('blocked'), c.blocked || 0, (c.blocked || 0) ? 'warn' : ''),
    kpi(t('failed'), c.failed || 0, (c.failed || 0) ? 'bad' : ''),
    kpi(t('alerts'), (sys.health && sys.health.risk_alerts && sys.health.risk_alerts.count) ?? '—', 'bad'),
    kpi(t('dispatch'), disp.open ? t('open') : t('closed'), disp.open ? 'good' : 'warn'));
  wrap.append(hero);
  const grid = H('div', { class: 'home-grid' });
  // left: owner decisions + activity
  const left = H('div', {});
  const cd = H('div', { class: 'card' }, H('h3', {}, t('ownerq')));
  if (!dec.length) cd.append(H('div', { class: 'op-empty' }, t('empty')));
  else dec.slice(0, 5).forEach(d => cd.append(H('div', { class: 'dec-card' }, H('span', { class: 'dec-pin' }), H('div', { class: 'dec-t' }, d.title, H('div', { class: 'dec-m' }, t('waiting'))))));
  left.append(cd);
  const ac = H('div', { class: 'card', style: 'margin-top:14px' }, H('h3', {}, H('span', { class: 'op-pulse' }), t('activity')));
  const acts = rm.activity || [];
  if (!acts.length) ac.append(H('div', { class: 'op-empty' }, t('notmsr')));
  else acts.slice(0, 8).forEach(a => ac.append(H('div', { class: 'op-arow' }, H('span', { class: 'op-dot', style: `background:${/FAIL/i.test(a.text) ? '#d66a6a' : '#7aa2d8'}` }), H('span', { class: 'op-atime' }, shortTs(a.ts, lang)), H('span', { class: 'op-atext' }, a.text))));
  left.append(ac);
  grid.append(left);
  // right: work + health
  const right = H('div', {});
  const wk = H('div', { class: 'card' }, H('h3', {}, t('work')));
  const decN = dec.length;
  [['owner_wait', (c.owner_wait || 0) + decN, '#d6a94a'], ['running', c.running || 0, '#7aa2d8'], ['review', c.review || 0, '#5fb8ac'], ['blocked', c.blocked || 0, '#d68b5a'], ['failed', c.failed || 0, '#d66a6a'], ['done', c.done || 0, '#5aa17a']]
    .forEach(([k, v, col]) => wk.append(H('div', { class: 'op-row', style: v ? '' : 'opacity:.5' }, H('span', { class: 'op-dot', style: `background:${col}` }), H('span', { class: 'op-lbl' }, t(k === 'owner_wait' ? 'needs' : k)), H('span', { class: 'op-ct' }, String(v)))));
  right.append(wk);
  const hc = H('div', { class: 'card', style: 'margin-top:14px' }, H('h3', {}, t('health')));
  const gl = sys.golive, ra = sys.health && sys.health.risk_alerts, fl = rm.roles && rm.roles.fleet;
  const kv = (k, v, warn) => H('div', { class: 'op-row' }, H('span', { class: 'op-lbl' }, k), H('span', { class: 'op-ct' + (warn ? ' warn' : '') }, v));
  if (gl) hc.append(kv(t('golive'), (gl.passed ?? '—') + '/' + (gl.total ?? '—') + (gl.freshness ? ' · ' + gl.freshness.freshness : ''), gl.freshness && gl.freshness.freshness === 'STALE'));
  if (ra) hc.append(kv(t('alerts'), String(ra.count ?? t('notmsr')), (ra.count || 0) > 0));
  if (fl) hc.append(kv(t('fleet'), (fl.total_loaded ?? '—') + '/' + (fl.total_known ?? '—'), fl.freshness && fl.freshness.freshness === 'STALE'));
  hc.append(kv(t('dispatch'), disp.open ? t('open') : t('closed'), !disp.open));
  right.append(hc);
  grid.append(right);
  wrap.append(grid);
  mount.append(wrap);
}
export function renderDecisions(mount, rm, lang) {
  const t = (k) => (HL[lang] || HL.en)[k] || k;
  mount.replaceChildren();
  const dec = (rm.decisions && rm.decisions.items) || [];
  const wrap = H('div', { class: 'home' });
  const cd = H('div', { class: 'card' }, H('h3', {}, t('ownerq') + ' · ' + dec.length));
  if (!dec.length) cd.append(H('div', { class: 'op-empty' }, t('empty')));
  else dec.forEach(d => cd.append(H('div', { class: 'dec-card' }, H('span', { class: 'dec-pin' }), H('div', { class: 'dec-t' }, d.title, H('div', { class: 'dec-m' }, t('waiting') + (d.card ? ' · ' + d.card + '.md' : ''))))));
  wrap.append(cd);
  mount.append(wrap);
}

// ── WHY: directed decision trace (FounderOS hex idiom, causal top-down) ───────────────
const AUTH_COLOR = { DETERMINISTIC: '#d66a6a', LLM: '#8f7bff', NONE: '#7aa2d8' };
const STAT_COLOR = { PASS: '#5aa17a', BLOCK: '#d66a6a', UNEVIDENCED: '#d6a94a', ABSENT: '#5a6480', PAPER: '#d6a94a', LIVE: '#5fb8ac', RECENT: '#5fb8ac', MARKET: '#7aa2d8', UNKNOWN: '#6b7690' };
const TIER = { object: 0, source: 1, evidence: 2, fact: 3, gate: 4, llm: 4, decision: 5, result: 6 };

const WKIND = { ru: { object: 'ОБЪЕКТ', source: 'ИСТОЧНИК', evidence: 'ДОКАЗАТЕЛЬСТВА', fact: 'ФАКТЫ', gate: 'ДЕТЕРМИНИР. ГЕЙТЫ', decision: 'РЕШЕНИЕ RISKPOLICY', result: 'РЕЗУЛЬТАТ', llm: 'LLM' }, en: { object: 'OBJECT', source: 'SOURCE', evidence: 'EVIDENCE', fact: 'FACTS', gate: 'DETERMINISTIC GATES', decision: 'RISKPOLICY DECISION', result: 'RESULT', llm: 'LLM' } };
function renderWhyMobile(stage, why, lang, onSelect) {
  const kt = (k) => (WKIND[lang] || WKIND.en)[k] || k;
  stage.replaceChildren();
  const wrap = H('div', { class: 'whym' });
  if (why.trace_partial) wrap.append(H('div', { class: 'whym-llm', style: 'border-style:solid;border-color:rgba(214,169,74,.4);color:#d6a94a;margin:0 auto 12px' }, (lang === 'ru' ? 'ТРАССА НЕПОЛНАЯ · TVL-floor не доказан (static)' : 'TRACE PARTIAL · TVL floor unevidenced (static)')));
  const order = ['object', 'source', 'evidence', 'fact', 'gate', 'decision', 'result'];
  const byKind = {}; why.nodes.forEach(n => (byKind[n.kind] = byKind[n.kind] || []).push(n));
  order.forEach((kind, gi) => {
    const group = byKind[kind]; if (!group || !group.length) return;
    const card = H('div', { class: 'whym-stage' });
    card.append(H('div', { class: 'whym-h' }, kt(kind)));
    group.forEach(n => {
      const stc = STAT_COLOR[n.status] || '#7aa2d8';
      const shape = n.kind === 'gate' ? 'sq' : n.kind === 'decision' ? 'di' : n.kind === 'result' ? 'ci' : 'hx';
      card.append(H('div', { class: 'whym-row', onclick: () => onSelect && onSelect(n) },
        H('span', { class: 'whym-mk ' + shape, style: `border-color:${AUTH_COLOR[n.authority] || '#7aa2d8'}` }),
        H('span', { class: 'whym-lbl' }, n.label),
        H('span', { class: 'whym-st', style: `color:${stc}` }, n.status)));
    });
    wrap.append(card);
    if (gi < order.length - 1 && byKind[order[gi + 1]]) wrap.append(H('div', { class: 'whym-arrow' }, '↓'));
  });
  // LLM side-status (absent, no authority)
  const llm = (byKind.llm || [])[0];
  if (llm) wrap.append(H('div', { class: 'whym-llm', onclick: () => onSelect && onSelect(llm) }, H('span', { class: 'whym-mk hx', style: 'border-color:#8f7bff;border-style:dashed' }), H('span', {}, 'LLM · ' + (lang === 'ru' ? 'БЕЗ ПОЛНОМОЧИЙ' : 'NO AUTHORITY') + ' · ' + llm.status)));
  stage.append(wrap);
}
export function renderWhy(stage, why, lang, onSelect) {
  const t = (k) => (L[lang] || L.en)[k] || (L.en[k]) || k;
  if (window.innerWidth <= 860) return renderWhyMobile(stage, why, lang, onSelect);
  stage.replaceChildren();
  const W = stage.clientWidth, Hh = stage.clientHeight;
  const nodes = why.nodes.map(n => ({ ...n }));
  const byId = {}; nodes.forEach(n => byId[n.id] = n);
  // layout: tiers top→bottom, spread within tier
  const tiers = {}; nodes.forEach(n => { const ti = TIER[n.kind] ?? 3; (tiers[ti] = tiers[ti] || []).push(n); });
  const maxTier = Math.max(...Object.keys(tiers).map(Number));
  const padTop = 96, padBot = 60; const rowH = (Hh - padTop - padBot) / maxTier;
  Object.entries(tiers).forEach(([ti, arr]) => { const y = padTop + rowH * Number(ti); const gap = W / (arr.length + 1); arr.forEach((n, i) => { n.x = gap * (i + 1); n.y = y; }); });

  const svg = S('svg', { width: '100%', height: '100%', viewBox: `0 0 ${W} ${Hh}` });
  const defs = S('defs');
  const grid = S('pattern', { id: 'wgrid', width: 46, height: 46, patternUnits: 'userSpaceOnUse' });
  grid.append(S('path', { d: 'M 46 0 L 0 0 0 46', fill: 'none', stroke: 'rgba(120,150,200,.05)', 'stroke-width': 1 })); defs.append(grid);
  const marker = S('marker', { id: 'arw', markerWidth: 7, markerHeight: 7, refX: 6, refY: 3, orient: 'auto' });
  marker.append(S('path', { d: 'M0,0 L6,3 L0,6 Z', fill: 'rgba(150,170,210,.5)' })); defs.append(marker);
  svg.append(defs);
  svg.append(S('rect', { width: W, height: Hh, fill: '#06080e' }), S('rect', { width: W, height: Hh, fill: 'url(#wgrid)' }));

  // edges (directed, arced)
  const gE = S('g', {});
  why.edges.forEach(e => { const a = byId[e.source], b = byId[e.target]; if (!a || !b) return; const dashed = byId[e.target].authority === 'LLM' || byId[e.source].authority === 'LLM'; gE.append(S('path', { d: edgeArc({ x: a.x, y: a.y + 16 }, { x: b.x, y: b.y - 18 }, 0.06), fill: 'none', stroke: dashed ? 'rgba(143,123,255,.4)' : 'rgba(150,170,210,.28)', 'stroke-width': 1.2, 'stroke-dasharray': dashed ? '3 3' : null, 'marker-end': 'url(#arw)' })); });
  svg.append(gE);

  // nodes: shape by kind — hex(data), square(gate/deterministic), diamond(decision), circle(result), dashed(llm)
  const gN = S('g', {});
  nodes.forEach(n => {
    const acc = AUTH_COLOR[n.authority] || '#7aa2d8';
    const stc = STAT_COLOR[n.status] || '#7aa2d8';
    const g = S('g', { style: 'cursor:pointer', transform: `translate(${n.x},${n.y})` });
    g.addEventListener('click', () => onSelect && onSelect(n));
    let shape;
    if (n.kind === 'gate') shape = S('rect', { x: -15, y: -13, width: 30, height: 26, rx: 3, fill: 'rgba(10,14,24,.85)', stroke: acc, 'stroke-width': 1.6 });
    else if (n.kind === 'decision') shape = S('polygon', { points: '0,-18 18,0 0,18 -18,0', fill: 'rgba(10,14,24,.85)', stroke: acc, 'stroke-width': 1.6 });
    else if (n.kind === 'result') shape = S('circle', { r: 14, fill: 'rgba(10,14,24,.85)', stroke: stc, 'stroke-width': 1.6 });
    else if (n.kind === 'llm') shape = S('polygon', { points: hexPts(13), fill: 'rgba(20,16,34,.7)', stroke: acc, 'stroke-width': 1.4, 'stroke-dasharray': '3 2.4' });
    else shape = S('polygon', { points: hexPts(n.kind === 'object' ? 16 : 12), fill: 'rgba(10,14,24,.82)', stroke: acc, 'stroke-width': 1.3 });
    // status ring
    const ring = S('circle', { r: 22, fill: 'none', stroke: stc, 'stroke-width': 1, opacity: .35, 'stroke-dasharray': n.status === 'UNEVIDENCED' ? '2 3' : (n.status === 'ABSENT' ? '1 4' : null) });
    const lbl = S('text', { 'text-anchor': 'middle', y: 34, fill: '#c8d2e8', 'font-size': 9.5, 'letter-spacing': '.03em', style: 'font-family:ui-monospace,Menlo,monospace' }, n.label);
    const st = S('text', { 'text-anchor': 'middle', y: 45, fill: stc, 'font-size': 8, 'letter-spacing': '.1em', style: 'font-family:ui-monospace,Menlo,monospace;text-transform:uppercase' }, n.status);
    g.append(ring, shape, lbl, st); gN.append(g);
  });
  svg.append(gN);
  stage.append(svg);
}
