// Earn DeFi UNIVERSE — adapts the ACTUAL FounderOS /brain visual system.
// Engine + layout math reused/ported from Bennettxai/FounderOS-DEMO @ ad46d772 (MIT):
//   vendor/d3-force.js (glide+collide) · vendor/founderos_layout.js (radialRestLayout, hexPts,
//   edgeArc, responsiveRingR — COPY+ADAPT). Node tiers/hex/rings/arced-edges/mono-monochrome
//   palette mirror KnowledgeGraph.tsx. Earn DeFi domain model + real-data binding is NEW_GLUE.
// Read-only. UI ≠ canonical truth.
import { forceSimulation, forceCollide, forceX, forceY } from './vendor/d3-force.js';
import { radialRestLayout, hexPts, edgeArc, responsiveRingR } from './vendor/founderos_layout.js';
import { renderSystem, renderWhy, renderHome, renderDecisions } from './syswhy.js';
import { renderCapital, renderStrategies, renderVoice, renderSlice, renderCompare } from './surfaces.js';
import { renderProjects, renderSearch, renderWork, renderResearch, openCommand } from './studio_core.js';

const SVGNS = 'http://www.w3.org/2000/svg';
const qs = new URLSearchParams(location.search);
const STATE = {
  lang: qs.get('lang') || localStorage.getItem('sos.lang') || 'ru',
  mode: qs.get('mode') || 'universe',
  focus: null, focusDomain: null, model: null, view: { x: 0, y: 0, k: 1 },
  reduceMotion: qs.get('rm') === '1',
};
// Earn DeFi domains → ring pillars (order = clockwise from top)
const DOMAIN_ORDER = ['opportunities', 'factory', 'capital', 'risk', 'system'];
const DOMAIN_HUB = { opportunities: 'opps', factory: 'factory', capital: 'capital', risk: 'risk', system: 'system' };

const T = {
  ru: { universe: 'Вселенная', system: 'Система', why: 'Почему?', ro: 'ТОЛЬКО ЧТЕНИЕ', reset: 'СБРОС', all: 'ВСЁ',
    legend: 'Живой граф реального состояния Earn DeFi · клик — фокус и раскрытие · только чтение',
    prov: 'ИСТОЧНИК', track: 'КОНТУР', apy: 'ДОХОДНОСТЬ', tvl: 'TVL', status: 'СТАТУС', fresh: 'СВЕЖЕСТЬ',
    evid: 'доказано', unevid: 'НЕ ДОКАЗАНО', why: 'ПОЧЕМУ?', evidence: 'ДОКАЗАТЕЛЬСТВА', details: 'ОТКРЫТЬ',
    dir: 'СПРАВОЧНИК', tracks: 'КОНТУРЫ',
    d: { opportunities: 'ВОЗМОЖНОСТИ', factory: 'ФАБРИКА / R&D', capital: 'КАПИТАЛ', risk: 'РИСК', system: 'СИСТЕМА', core: 'ЯДРО' },
    tk: { MARKET: 'РЫНОК', PAPER: 'БУМАГА', STUDIO: 'STUDIO', UNKNOWN: 'НЕ ИЗМ.', SHADOW: 'ТЕНЬ' } },
  en: { universe: 'Universe', system: 'System', why: 'Why?', ro: 'READ ONLY', reset: 'RESET', all: 'ALL',
    legend: 'Live graph of real Earn DeFi state · click to focus & reveal · read-only',
    prov: 'SOURCE', track: 'TRACK', apy: 'YIELD', tvl: 'TVL', status: 'STATUS', fresh: 'FRESHNESS',
    evid: 'evidenced', unevid: 'UNEVIDENCED', why: 'WHY?', evidence: 'EVIDENCE', details: 'OPEN',
    dir: 'DIRECTORY', tracks: 'TRACKS',
    d: { opportunities: 'OPPORTUNITIES', factory: 'FACTORY / R&D', capital: 'CAPITAL', risk: 'RISK', system: 'SYSTEM', core: 'CORE' },
    tk: { MARKET: 'MARKET', PAPER: 'PAPER', STUDIO: 'STUDIO', UNKNOWN: 'NOT MSR', SHADOW: 'SHADOW' } },
};
const tr = (k) => (T[STATE.lang] && T[STATE.lang][k]) ?? T.en[k] ?? k;
const dname = (d) => (T[STATE.lang].d[d] || T.en.d[d] || d);
const tkname = (t) => (T[STATE.lang].tk[t] || t);

// Restrained, near-monochrome accents (stroke/marker only, never big fills)
const TRACK = { MARKET: '#7aa2d8', STUDIO: '#5fb8ac', PAPER: '#d6a94a', UNKNOWN: '#6b7690', SHADOW: '#8f7bff' };
const DOMAIN_ACCENT = { core: '#e8edf7', opportunities: '#7aa2d8', risk: '#d66a6a', capital: '#d6a94a', system: '#5fb8ac', factory: '#8a93ac' };

const svg = (t, a = {}, ...k) => { const n = document.createElementNS(SVGNS, t); for (const [key, v] of Object.entries(a)) if (v != null) n.setAttribute(key, v); for (const c of k) if (c != null) n.append(c.nodeType ? c : document.createTextNode(c)); return n; };
const H = (t, a = {}, ...k) => { const n = document.createElement(t); for (const [key, v] of Object.entries(a)) { if (v == null) continue; if (key === 'class') n.className = v; else if (key.startsWith('on')) n.addEventListener(key.slice(2), v); else n.setAttribute(key, v); } for (const c of k) if (c != null) n.append(c.nodeType ? c : document.createTextNode(c)); return n; };

async function load() {
  const j = (u) => fetch(u + '?_=' + Date.now()).then(r => r.ok ? r.json() : null).catch(() => null);
  [STATE.model, STATE.rm, STATE.why, STATE.capital, STATE.strategies, STATE.slice, STATE.slicePendle, STATE.compare, STATE.context, STATE.projects] = await Promise.all([
    j('./universe.json'), j('./read_model.json'), j('./why_aave.json'), j('./capital.json'), j('./strategies.json'),
    j('./slice_aave.json'), j('./slice_pendle.json'), j('./compare.json'), j('./project_context.json'), j('./projects.json')]);
  [STATE.research, STATE.repoStatus, STATE.taskLinks] = await Promise.all([j('./research.json'), j('./repo_status.json'), j('./task_links.json')]);
}
// ── OS navigation model ──────────────────────────────────────────────────────────────
const GRAPH_VIEWS = new Set(['universe', 'opportunities', 'risk', 'research']);
const VIEWS = [
  { id: 'home', grp: 'os', icon: '◎', mode: 'home' },
  { id: 'projects', grp: 'os', icon: '◈', mode: 'projects' },
  { id: 'work', grp: 'os', icon: '▤', mode: 'work' },
  { id: 'decisions', grp: 'os', icon: '◆', mode: 'decisions' },
  { id: 'research', grp: 'os', icon: '⚗', mode: 'research' },
  { id: 'memory', grp: 'os', icon: '⌕', mode: 'memory' },
  { id: 'system', grp: 'os', icon: '❖', mode: 'system' },
  { id: 'capital', grp: 'defi', icon: '▤', mode: 'capital' },        // read-only financial surface (Owner Remote)
  { id: 'strategies', grp: 'defi', icon: '⑃', mode: 'strategies' },
  { id: 'slice', grp: 'defi', icon: '▦', mode: 'slice' },
  { id: 'compare', grp: 'defi', icon: '⚖', mode: 'compare' },
  { id: 'voice', grp: 'defi', icon: '◉', mode: 'voice' },
  { id: 'universe', grp: 'graph', icon: '✦', mode: 'universe' },
  { id: 'opportunities', grp: 'graph', icon: '◇', mode: 'universe', focus: 'opportunities' },
  { id: 'risk', grp: 'graph', icon: '△', mode: 'universe', focus: 'risk' },
  { id: 'rnd', grp: 'graph', icon: '⚗', mode: 'universe', focus: 'factory' },
  { id: 'why', grp: 'intel', icon: '?', mode: 'why' },
  { id: 'slicep', grp: 'intel', icon: '▦', mode: 'slicep' },
  { id: 'evidence', grp: 'intel', icon: '⊹', mode: 'why' },
];
const VIEW_LABEL = {
  ru: { os: 'СТУДИЯ OS', defi: 'EARN DEFI', graph: 'ГРАФ', intel: 'ТРАССА', home: 'Обзор', projects: 'Проекты', work: 'Работа', memory: 'Память', universe: 'Вселенная', opportunities: 'Возможности', capital: 'Капитал', strategies: 'Стратегии', voice: 'Голос', risk: 'Риск', system: 'Система', decisions: 'Решения', research: 'Исследования', rnd: 'R&D', why: 'Почему?', slice: 'Срез Aave', slicep: 'Срез Pendle', compare: 'Сравнение', evidence: 'Доказательства', search: 'поиск' },
  en: { os: 'STUDIO OS', defi: 'EARN DEFI', graph: 'GRAPH', intel: 'TRACE', home: 'Overview', projects: 'Projects', work: 'Work', memory: 'Memory', universe: 'Universe', opportunities: 'Opportunities', capital: 'Capital', strategies: 'Strategies', voice: 'Voice', risk: 'Risk', system: 'System', decisions: 'Decisions', research: 'Research', rnd: 'R&D', why: 'Why?', slice: 'Aave Slice', slicep: 'Pendle Slice', compare: 'Compare', evidence: 'Evidence', search: 'search' },
};
const vlabel = (k) => (VIEW_LABEL[STATE.lang] || VIEW_LABEL.en)[k] || k;
// MOBILE Owner Remote bottom nav: OVERVIEW · CAPITAL · VOICE(central) · STRATEGIES · SYSTEM
const BOTTOM = ['home', 'capital', 'voice', 'strategies', 'system'];

function applyView(viewId) {
  const v = VIEWS.find(x => x.id === (viewId || STATE.viewId)) || VIEWS[0];
  STATE.viewId = v.id; STATE.mode = v.mode; STATE.focusDomain = v.focus || null; STATE.focus = v.focus ? DOMAIN_HUB[v.focus] : null;
  document.body.className = (STATE.reduceMotion ? 'rm ' : '') + 'view-' + v.id + (GRAPH_VIEWS.has(v.id) || v.mode === 'system' ? ' mode-graph' : '');
  document.body.classList.remove('drawer');
  document.getElementById('panel').classList.remove('open');
  if (v.mode === 'home') { renderHome(document.getElementById('homeview'), STATE.rm || {}, STATE.lang); chrome(); }
  else if (v.mode === 'decisions') { renderDecisions(document.getElementById('decisionsview'), STATE.rm || {}, STATE.lang); chrome(); }
  else if (v.mode === 'capital') { renderCapital(document.getElementById('capitalview'), STATE.capital, STATE.lang, navBridge()); chrome(); }
  else if (v.mode === 'strategies') { renderStrategies(document.getElementById('strategiesview'), STATE.strategies, STATE.lang, navBridge()); chrome(); }
  else if (v.mode === 'voice') { renderVoice(document.getElementById('voiceview'), { lang: STATE.lang, nav: navBridge() }); chrome(); }
  else if (v.mode === 'slice') { renderSlice(document.getElementById('sliceview'), STATE.slice, STATE.lang); chrome(); }
  else if (v.mode === 'slicep') { renderSlice(document.getElementById('sliceview'), STATE.slicePendle, STATE.lang); chrome(); }
  else if (v.mode === 'compare') { renderCompare(document.getElementById('compareview'), STATE.compare, STATE.lang); chrome(); }
  else if (v.mode === 'projects') { renderProjects(document.getElementById('projectsview'), STATE.context, STATE.projects, STATE.lang, navBridge(), STATE.repoStatus); chrome(); }
  else if (v.mode === 'work') { renderWork(document.getElementById('workview'), STATE.rm || {}, STATE.lang, navBridge(), STATE.taskLinks); chrome(); }
  else if (v.mode === 'research') { renderResearch(document.getElementById('researchview'), STATE.research, STATE.lang); chrome(); }
  else if (v.mode === 'memory') { chrome(); const mv = document.getElementById('memoryview'); if (STATE.searchIndex) renderSearch(mv, STATE.searchIndex, STATE.lang); else { mv.replaceChildren(); fetch('./search_index.json').then(r => r.json()).then(ix => { STATE.searchIndex = ix; if (STATE.viewId === 'memory') renderSearch(mv, ix, STATE.lang); }).catch(() => { mv.textContent = 'search index unavailable'; }); } }
  else if (v.mode === 'why') showWhy();
  else { build(); if (v.focus) { applyFocus(); renderPanel(nodeById[STATE.focus]); } }
}

// Bridge given to Owner-Remote surfaces: navigate (GREEN), answer read-only queries, open entity sheet.
function navBridge() {
  return {
    go: (view) => applyView(view),
    answer: (view, _text) => answerQuery(view),
    openEntity: (kind, id, data) => renderEntitySheet(kind, id, data),
  };
}
function answerQuery(view) {
  const ru = STATE.lang === 'ru';
  if (view === 'capital' && STATE.capital && STATE.capital.present) {
    const c = STATE.capital;
    return (ru ? 'Капитал (PAPER, виртуальный): ' : 'Capital (PAPER, virtual): ')
      + fmtUsd(c.total_usd) + (ru ? ' · размещено ' : ' · deployed ') + fmtUsd(c.deployed_usd)
      + (ru ? ' · свободно ' : ' · cash ') + fmtUsd(c.cash_usd)
      + ' · ' + (c.allocations || []).length + (ru ? ' позиций.' : ' positions.');
  }
  if (view === 'strategies' && STATE.strategies && STATE.strategies.present)
    return (ru ? 'Стратегий в каталоге: ' : 'Strategies in catalogue: ') + STATE.strategies.total + (ru ? ' (советательные, paper).' : ' (advisory, paper).');
  if (view === 'system' && STATE.rm && STATE.rm.system) {
    const d = STATE.rm.system.dispatch;
    return (ru ? 'Система: диспетчер ' : 'System: dispatch ') + (d && d.open ? 'OPEN' : 'CLOSED') + '.';
  }
  return ru ? 'Только чтение. Открой раздел для подробностей.' : 'Read-only. Open the section for detail.';
}
function renderEntitySheet(kind, id, data) {
  const host = window.innerWidth <= 860 ? document.getElementById('sheet') : document.getElementById('panel');
  const ru = STATE.lang === 'ru';
  const wrap = H('div', {});
  const title = data && (data.name || data.protocol || id) || id;
  wrap.append(H('div', { class: 'phead' }, H('span', { class: 'pmark' }),
    H('div', { class: 'ptitle' }, H('strong', {}, String(title)), H('span', { class: 'psub' }, kind.toUpperCase())),
    H('button', { class: 'px', onclick: () => { host.classList.remove('open'); host.replaceChildren(); } }, '×')));
  const row = (k, v, cls) => H('div', { class: 'prow' }, H('span', { class: 'pk' }, k), H('span', { class: 'pv ' + (cls || '') }, v == null ? '—' : String(v)));
  if (kind === 'protocol') {
    if (data.track) wrap.append(H('div', { class: 'ptrack' }, H('span', { class: 'pill' }, data.track)));
    wrap.append(row('$', fmtUsd(data.usd)));
    wrap.append(row(ru ? 'ДОХОДНОСТЬ' : 'YIELD', data.apy_pct != null ? data.apy_pct + '%' : (ru ? 'НЕИЗВЕСТНА' : 'UNKNOWN'), data.apy_evidenced ? '' : 'warn'));
    wrap.append(row(ru ? 'ИСТОЧНИК APY' : 'APY SOURCE', data.apy_source || 'UNKNOWN', data.apy_evidenced ? '' : 'warn'));
    if (data.as_of) wrap.append(row(ru ? 'НА МОМЕНТ' : 'AS OF', String(data.as_of).slice(0, 19)));
  } else if (kind === 'strategy') {
    wrap.append(H('div', { class: 'ptrack' }, H('span', { class: 'pill' }, data.tier || '—'), H('span', { class: 'pill' }, (data.status || 'UNKNOWN').toUpperCase())));
    wrap.append(row(ru ? 'ЦЕЛЬ APY' : 'TARGET APY', (data.apy_min != null && data.apy_max != null) ? data.apy_min + '–' + data.apy_max + '%' : (data.apy_mid != null ? data.apy_mid + '%' : '—')));
    if (data.max_drawdown_pct != null) wrap.append(row(ru ? 'МАКС. ПРОСАДКА' : 'MAX DRAWDOWN', '−' + data.max_drawdown_pct + '%'));
    if (data.type) wrap.append(row(ru ? 'ТИП' : 'TYPE', data.type));
    if (data.tags && data.tags.length) wrap.append(row(ru ? 'ТЕГИ' : 'TAGS', data.tags.join(', ')));
  }
  // WHY — only where a real trace exists (aave)
  const hasWhy = kind === 'protocol' && /aave/i.test(id);
  const acts = H('div', { class: 'pacts' });
  if (hasWhy) acts.append(H('button', { class: 'pact', onclick: () => applyView('why') }, ru ? 'ПОЧЕМУ?' : 'WHY?'));
  else acts.append(H('button', { class: 'pact', disabled: true, title: ru ? 'трасса недоступна' : 'no trace' }, ru ? 'ТРАССА НЕТ' : 'NO TRACE'));
  wrap.append(acts);
  if (data.provenance) wrap.append(H('div', { class: 'prov' }, (ru ? 'ИСТОЧНИК · ' : 'SOURCE · ') + data.provenance));
  host.replaceChildren(wrap); host.classList.add('open');
}
function showWhy() {
  const t = (k, f) => { const M = { ru: { partial: 'ТРАССА НЕПОЛНАЯ', det: 'ДЕТЕРМИНИР. ГЕЙТ', llm: 'LLM · без полномочий', data: 'ДАННЫЕ / ФАКТ' }, en: { partial: 'TRACE PARTIAL', det: 'DETERMINISTIC GATE', llm: 'LLM · no authority', data: 'DATA / FACT' } }; return (M[STATE.lang] || M.en)[k] || f; };
  chrome();
  const w = STATE.why;
  const ban = document.getElementById('whybanner');
  ban.textContent = w && w.trace_partial ? (t('partial') + ' · ' + (STATE.lang === 'ru' ? 'TVL-floor не доказан (static)' : 'TVL floor unevidenced (static)')) : (w ? (STATE.lang === 'ru' ? 'ТРАССА ПОЛНАЯ' : 'TRACE COMPLETE') : '');
  const lg = document.getElementById('whylegend'); lg.replaceChildren();
  [['wl-det', t('det')], ['wl-llm', t('llm')], ['wl-data', t('data')]].forEach(([c, l]) => lg.append(H('b', {}, H('i', { class: c }), l)));
  if (w) renderWhy(document.getElementById('whystage'), w, STATE.lang, (n) => renderWhyPanel(n));
}
function renderWhyPanel(n) {
  const host = window.innerWidth <= 860 ? document.getElementById('sheet') : document.getElementById('panel');
  const AUTH = { DETERMINISTIC: STATE.lang === 'ru' ? 'ДЕТЕРМИНИРОВАННЫЙ' : 'DETERMINISTIC', LLM: 'LLM', NONE: STATE.lang === 'ru' ? 'ДАННЫЕ' : 'DATA' };
  const acc = n.authority === 'DETERMINISTIC' ? '#d66a6a' : n.authority === 'LLM' ? '#8f7bff' : '#7aa2d8';
  const wrap = H('div', {});
  wrap.append(H('div', { class: 'phead' }, H('span', { class: 'pmark', style: `border-color:${acc}` }), H('div', { class: 'ptitle' }, H('strong', {}, n.label), H('span', { class: 'psub' }, (n.kind || '').toUpperCase())), H('button', { class: 'px', onclick: () => { host.classList.remove('open'); host.replaceChildren(); } }, '×')));
  wrap.append(H('div', { class: 'ptrack' }, H('span', { class: 'pill', style: `color:${acc};border-color:${acc}` }, AUTH[n.authority] || n.authority)));
  wrap.append(H('div', { class: 'prow' }, H('span', { class: 'pk' }, STATE.lang === 'ru' ? 'СТАТУС' : 'STATUS'), H('span', { class: 'pv' + (['UNEVIDENCED', 'BLOCK', 'ABSENT', 'PAPER'].includes(n.status) ? ' warn' : '') }, n.status)));
  if (n.detail) wrap.append(H('div', { class: 'prov', style: 'color:var(--ink2)' }, n.detail));
  if (n.provenance) wrap.append(H('div', { class: 'prov' }, (STATE.lang === 'ru' ? 'ИСТОЧНИК' : 'SOURCE') + ' · ' + n.provenance));
  host.replaceChildren(wrap); host.classList.add('open');
}

let sim, gRoot, W, Hh, nodeById = {}, nodeEls = {}, edgeEls = [], ringEls = [];

const isMobile = () => window.innerWidth <= 860;
function activeGraph() {
  const m = STATE.model;
  if (STATE.mode === 'system') {
    const keep = new Set(['earndefi']); m.nodes.forEach(n => { if (n.domain === 'system' || n.id === 'earndefi') keep.add(n.id); });
    return { nodes: m.nodes.filter(n => keep.has(n.id)).map(n => ({ ...n })), edges: m.edges.filter(e => keep.has(sid(e)) && keep.has(tid(e))).map(e => ({ ...e })) };
  }
  // MOBILE Universe: domains-only by default; tap a domain → that domain + its children only
  if (isMobile()) {
    const keep = new Set(['earndefi']);
    m.nodes.forEach(n => { if (n.id === DOMAIN_HUB[n.domain]) keep.add(n.id); });   // primary domain hubs only
    if (STATE.focusDomain) m.nodes.forEach(n => { if (n.domain === STATE.focusDomain) keep.add(n.id); });
    return { nodes: m.nodes.filter(n => keep.has(n.id)).map(n => ({ ...n })), edges: m.edges.filter(e => keep.has(sid(e)) && keep.has(tid(e))).map(e => ({ ...e })) };
  }
  return { nodes: m.nodes.map(n => ({ ...n })), edges: m.edges.map(e => ({ ...e })) };
}
const sid = e => e.source.id || e.source, tid = e => e.target.id || e.target;

// Equal-sector radial layout — symmetric, canvas-filling, deterministic (no density skew).
function computeRest(nodes) {
  const domains = STATE.mode === 'system' ? ['system'] : DOMAIN_ORDER.filter(d => nodes.some(n => n.domain === d));
  const cx = W / 2, cy = Hh / 2;
  const scale = STATE.mode === 'system' ? 1.15 : (isMobile() ? 0.82 : 1.34);   // fill the canvas (inset on mobile)
  const R = responsiveRingR(W, Hh).map(r => r * scale);
  const pos = new Map(); pos.set('earndefi', { x: cx, y: cy });
  const polar = (r, a) => ({ x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) });
  const N = Math.max(1, domains.length), start = -Math.PI / 2;
  const others = domains.filter(d => d !== STATE.focusDomain);
  domains.forEach((d, i) => {
    const focused = STATE.focusDomain === d, recede = STATE.focusDomain && !focused;
    let center = start + i * (2 * Math.PI / N), half = (Math.PI / N) * 0.82, hubR = R[1], childR = R[2];
    if (focused) { center = -Math.PI / 2; half = Math.PI * 0.6; hubR = R[1] * 0.8; childR = R[2] * 1.12; }
    else if (recede) { const j = others.indexOf(d); center = Math.PI / 2 + (j - (others.length - 1) / 2) * 0.5; half = 0.12; hubR = R[1] * 0.7; childR = R[1] * 0.95; }
    pos.set(DOMAIN_HUB[d], polar(hubR, center));
    const kids = nodes.filter(n => n.domain === d && n.id !== DOMAIN_HUB[d]).map(n => n.id);
    kids.forEach((id, k) => {
      const t = kids.length <= 1 ? 0 : (k / (kids.length - 1)) * 2 - 1;   // -1..1 across the sector
      const twoRow = kids.length > 8 && (k % 2 === 1);                     // de-crowd dense domains
      pos.set(id, polar(twoRow ? childR * 1.26 : childR, center + t * half));
    });
  });
  return pos;
}

function build() {
  const stage = document.getElementById('stage'); stage.innerHTML = '';
  W = stage.clientWidth; Hh = stage.clientHeight;
  const { nodes, edges } = activeGraph();
  nodeById = {}; nodes.forEach(n => nodeById[n.id] = n);

  const root = svg('svg', { width: '100%', height: '100%', viewBox: `0 0 ${W} ${Hh}` });
  const defs = svg('defs');
  // faint technical grid
  const gp = svg('pattern', { id: 'grid', width: 46, height: 46, patternUnits: 'userSpaceOnUse' });
  gp.append(svg('path', { d: 'M 46 0 L 0 0 0 46', fill: 'none', stroke: 'rgba(120,150,200,.06)', 'stroke-width': 1 }));
  defs.append(gp);
  const glow = svg('filter', { id: 'glow', x: '-60%', y: '-60%', width: '220%', height: '220%' });
  glow.append(svg('feGaussianBlur', { stdDeviation: 2.4, result: 'b' }), (() => { const m = svg('feMerge'); m.append(svg('feMergeNode', { in: 'b' }), svg('feMergeNode', { in: 'SourceGraphic' })); return m; })());
  defs.append(glow);
  root.append(defs);
  root.append(svg('rect', { x: 0, y: 0, width: W, height: Hh, fill: '#06080e' }));
  root.append(svg('rect', { x: 0, y: 0, width: W, height: Hh, fill: 'url(#grid)' }));

  gRoot = svg('g', {});
  root.append(gRoot);
  // concentric construction rings + radial spokes (the FounderOS structured canvas)
  const cx = W / 2, cy = Hh / 2; const _sc = STATE.mode === 'system' ? 1.15 : (isMobile() ? 1.0 : 1.34); const ringR = responsiveRingR(W, Hh).map(r => r * _sc);
  const gRings = svg('g', { opacity: .5 }); ringEls = [];
  ringR.slice(1).forEach((r, i) => { const c = svg('circle', { cx, cy, r, fill: 'none', stroke: 'rgba(120,150,200,.10)', 'stroke-width': 1, 'stroke-dasharray': i === 0 ? null : '2 6' }); gRings.append(c); ringEls.push(c); });
  for (let a = 0; a < 12; a++) { const ang = (a / 12) * Math.PI * 2; const R = ringR[ringR.length - 1]; gRings.append(svg('line', { x1: cx, y1: cy, x2: cx + R * Math.cos(ang), y2: cy + R * Math.sin(ang), stroke: 'rgba(120,150,200,.05)', 'stroke-width': 1 })); }
  gRoot.append(gRings);

  const gEdges = svg('g', {}), gNodes = svg('g', {});
  gRoot.append(gEdges, gNodes);

  edgeEls = edges.map(e => { const p = svg('path', { fill: 'none', stroke: 'rgba(150,170,210,.14)', 'stroke-width': 1 }); gEdges.append(p); return { e, p }; });

  nodeEls = {};
  nodes.forEach(n => {
    const isHub = n.id === 'earndefi' || n.id === DOMAIN_HUB[n.domain];   // only the PRIMARY domain hub
    const r = n.id === 'earndefi' ? 19 : isHub ? 12 : 7;
    const acc = isHub ? (DOMAIN_ACCENT[n.domain] || '#7aa2d8') : (TRACK[n.track] || '#7aa2d8');
    const g = svg('g', { class: 'gnode', style: 'cursor:pointer' });
    g.addEventListener('click', (ev) => { ev.stopPropagation(); onNodeClick(n); });
    const he = svg('polygon', { points: hexPts(r), fill: n.id === 'earndefi' ? 'rgba(232,237,247,.10)' : 'rgba(10,14,24,.82)', stroke: acc, 'stroke-width': isHub ? 1.5 : 1.1, 'stroke-dasharray': n.track === 'PAPER' ? '3 2.4' : (n.track === 'UNKNOWN' ? '1 3' : null), filter: isHub ? 'url(#glow)' : null });
    const label = svg('text', { class: 'nlabel', 'text-anchor': 'middle', y: r + 12, fill: isHub ? '#c8d2e8' : '#8792ab', 'font-size': n.id === 'earndefi' ? 12 : isHub ? 10.5 : 8.5, 'letter-spacing': isHub ? '.12em' : '.04em', style: `font-family:ui-monospace,Menlo,monospace;text-transform:${isHub ? 'uppercase' : 'none'}` }, isHub ? (n.id === 'earndefi' ? 'EARN DEFI' : dname(n.domain)) : n.label);
    if (!isHub) label.setAttribute('opacity', '0');   // leaf/secondary labels revealed on focus (no overlap)
    g.append(he, label);
    gNodes.append(g);
    nodeEls[n.id] = { g, he, label, r, acc, n, isHub };
  });
  stage.append(root);
  root.addEventListener('click', () => { STATE.focusDomain = null; onNodeClick(null); relayout(); });
  attachPanZoom(root);

  // rest positions on FounderOS rings; d3-force glides to them + de-overlaps
  const rest = computeRest(nodes);
  nodes.forEach(n => { const p = rest.get(n.id); if (p) { n.x = p.x; n.y = p.y; n.rx = p.x; n.ry = p.y; } });
  // radial hub-label anchoring — labels pushed outward along their radius so they never
  // collide (with the centre EARN DEFI label or with each other). Leaf labels stay hidden.
  if (!isMobile()) nodes.forEach(n => {
    const el = nodeEls[n.id]; if (!el || !el.isHub) return;
    if (n.id === 'earndefi') { el.label.setAttribute('x', 0); el.label.setAttribute('y', el.r + 15); el.label.setAttribute('text-anchor', 'middle'); return; }
    const ang = Math.atan2(n.ry - Hh / 2, n.rx - W / 2), dx = Math.cos(ang), dy = Math.sin(ang), gap = el.r + 12;
    el.label.setAttribute('x', (dx * gap).toFixed(1)); el.label.setAttribute('y', (dy * gap + 3.5).toFixed(1));
    el.label.setAttribute('text-anchor', dx > 0.25 ? 'start' : dx < -0.25 ? 'end' : 'middle');
  });
  sim = forceSimulation(nodes)
    .force('x', forceX(n => n.rx ?? W / 2).strength(n => n.id === 'earndefi' ? 1 : .5))
    .force('y', forceY(n => n.ry ?? Hh / 2).strength(n => n.id === 'earndefi' ? 1 : .5))
    .force('collide', forceCollide().radius(n => (n.id === 'earndefi' ? 26 : n.hub ? 18 : 11)).strength(.9));
  nodeById['earndefi'].fx = W / 2; nodeById['earndefi'].fy = Hh / 2;
  sim.on('tick', paint);
  for (let i = 0; i < 240; i++) sim.tick(); paint();
  if (STATE.reduceMotion) sim.stop(); else sim.alpha(.25).restart();
  chrome();
  if (STATE.mode === 'system' && STATE.rm) renderSystem(document.getElementById('syspanels'), STATE.rm, STATE.lang);
}

function relayout() {
  const nodes = Object.values(nodeById);
  const rest = computeRest(nodes);
  nodes.forEach(n => { const p = rest.get(n.id); if (p) { n.rx = p.x; n.ry = p.y; } });
  sim.force('x').x(n => n.rx ?? W / 2); sim.force('y').y(n => n.ry ?? Hh / 2);
  if (STATE.reduceMotion) { for (let i = 0; i < 200; i++) sim.tick(); paint(); } else sim.alpha(.55).restart();
}

function paint() {
  edgeEls.forEach(({ e, p }) => { const s = e.source, t = e.target; if (!s || s.x == null) return; p.setAttribute('d', edgeArc({ x: s.x, y: s.y }, { x: t.x, y: t.y }, 0.14)); });
  for (const id in nodeEls) { const n = nodeById[id]; if (!n || n.x == null) continue; nodeEls[id].g.setAttribute('transform', `translate(${round(n.x)},${round(n.y)})`); }
}
const round = v => Math.round(v * 10) / 10;

function onNodeClick(n) {
  if (n && n.hub && n.id !== 'earndefi') { STATE.focusDomain = n.domain; STATE.focus = n.id; relayout(); }
  else if (n && n.id === 'earndefi') { STATE.focusDomain = null; STATE.focus = null; relayout(); }
  else STATE.focus = n ? n.id : STATE.focus;
  applyFocus(); renderPanel(n);
}

function applyFocus() {
  const id = STATE.focus;
  const dom = STATE.focusDomain;
  const neigh = new Set();
  if (id) { neigh.add(id); STATE.model.edges.forEach(e => { const s = sid(e), t = tid(e); if (s === id) neigh.add(t); if (t === id) neigh.add(s); }); }
  for (const nid in nodeEls) {
    const nn = nodeById[nid]; const inDom = dom && (nn.domain === dom || nid === 'earndefi');
    const lit = !id && !dom ? true : (dom ? inDom : neigh.has(nid));
    nodeEls[nid].g.style.opacity = lit ? 1 : .16;
    // reveal leaf labels only for the focused/neighbour set (collision solved)
    if (!nn.hub) nodeEls[nid].label.setAttribute('opacity', (id === nid || (dom && nn.domain === dom)) ? '1' : '0');
  }
  edgeEls.forEach(({ e, p }) => { const s = sid(e), t = tid(e); const on = (!id && !dom) ? true : (dom ? (nodeById[s]?.domain === dom || nodeById[t]?.domain === dom || s === 'earndefi') : (s === id || t === id)); p.setAttribute('stroke', on && (id || dom) ? 'rgba(122,162,216,.5)' : 'rgba(150,170,210,.12)'); p.style.opacity = on ? 1 : .12; });
}

function renderPanel(n) {
  const host = window.innerWidth <= 860 ? document.getElementById('sheet') : document.getElementById('panel');
  const other = window.innerWidth <= 860 ? document.getElementById('panel') : document.getElementById('sheet');
  other.classList.remove('open'); other.replaceChildren();
  if (!n) { host.classList.remove('open'); host.replaceChildren(); return; }
  const acc = n.hub ? (DOMAIN_ACCENT[n.domain] || '#7aa2d8') : (TRACK[n.track] || '#7aa2d8');
  const kind = n.hub ? dname(n.domain) : (n.kind || '').toUpperCase();
  const row = (k, v, cls) => H('div', { class: 'prow' }, H('span', { class: 'pk' }, k), H('span', { class: 'pv ' + (cls || '') }, v));
  const wrap = H('div', {});
  wrap.append(H('div', { class: 'phead' }, H('span', { class: 'pmark', style: `border-color:${acc}` }), H('div', { class: 'ptitle' }, H('strong', {}, n.label), H('span', { class: 'psub' }, kind)), H('button', { class: 'px', onclick: () => { STATE.focus = null; STATE.focusDomain = n.hub ? null : STATE.focusDomain; applyFocus(); renderPanel(null); if (n.hub) relayout(); } }, '×')));
  wrap.append(H('div', { class: 'ptrack' }, H('span', { class: 'pill', style: `color:${acc};border-color:${acc}` }, tkname(n.track))));
  const m = n.metrics || {};
  const sec = (t) => wrap.append(H('div', { class: 'psec' }, t));
  if (m.apy_pct != null || m.tvl_usd != null) {
    sec('METRICS');
    if (m.apy_pct != null) wrap.append(row(tr('apy'), m.apy_pct + '%', m.apy_evidence === 'LIVE' ? '' : 'warn'));
    if (m.tvl_usd != null) wrap.append(row(tr('tvl'), fmtUsd(m.tvl_usd)));
    if (m.tvl_source) wrap.append(row('TVL src', m.tvl_source, m.tvl_evidenced ? '' : 'warn'));
  }
  if (m.paper_usd != null) { sec('CAPITAL'); wrap.append(row('$', Number(m.paper_usd).toLocaleString() + ' (PAPER)', 'warn')); }
  if (m.passed != null) { sec('GATES'); wrap.append(row('GoLive', m.passed + '/' + m.total)); if (m.track_days != null) wrap.append(row('track', m.track_days + 'd')); }
  if (m.missions != null) { sec('LEDGER'); wrap.append(row('missions', m.missions + ' · work ' + m.work_items)); wrap.append(row('dispatch', m.dispatch_open ? 'OPEN' : 'CLOSED', m.dispatch_open ? '' : 'warn')); }
  if (m.loaded != null) { sec('FLEET'); wrap.append(row('loaded', m.loaded + '/' + m.known)); }
  if (m.alerts != null) { sec('RISK'); wrap.append(row('alerts', String(m.alerts))); }
  sec(tr('status'));
  if (n.status) wrap.append(row('', n.status));
  const ev = (m.apy_evidence === 'LIVE' || m.tvl_evidenced);
  wrap.append(row(tr('track'), ev ? tr('evid') : tr('unevid'), ev ? '' : 'warn'));
  if (n.fresh) wrap.append(row(tr('fresh'), n.fresh, n.fresh === 'STALE' ? 'warn' : ''));
  const isAave = /aave/i.test(n.id || ''), isPendle = /pendle/i.test(n.id || '');
  const acts = H('div', { class: 'pacts' });
  acts.append(H('button', { class: 'pact', onclick: () => applyView('why') }, tr('why')));
  const detail = isAave ? 'slice' : isPendle ? 'slicep' : null;
  if (detail) acts.append(H('button', { class: 'pact', onclick: () => applyView(detail) }, STATE.lang === 'ru' ? 'ОТКРЫТЬ ДЕТАЛИ' : 'OPEN DETAIL'));
  else acts.append(H('button', { class: 'pact' }, tr('details')));
  if (isAave || isPendle) acts.append(H('button', { class: 'pact', onclick: () => applyView('compare') }, STATE.lang === 'ru' ? 'СРАВНИТЬ' : 'COMPARE'));
  wrap.append(acts);
  if (n.provenance) wrap.append(H('div', { class: 'prov' }, tr('prov') + ' · ' + n.provenance));
  host.replaceChildren(wrap); host.classList.add('open');
}

function attachPanZoom(root) {
  let drag = false, sx, sy;
  root.addEventListener('wheel', (ev) => { ev.preventDefault(); const k = Math.min(2.6, Math.max(.45, STATE.view.k * (1 - ev.deltaY * 0.0012))); STATE.view.k = k; applyTransform(); }, { passive: false });
  root.addEventListener('pointerdown', (ev) => { drag = true; sx = ev.clientX; sy = ev.clientY; });
  window.addEventListener('pointermove', (ev) => { if (!drag) return; STATE.view.x += ev.clientX - sx; STATE.view.y += ev.clientY - sy; sx = ev.clientX; sy = ev.clientY; applyTransform(); });
  window.addEventListener('pointerup', () => drag = false);
}
function applyTransform() { if (gRoot) gRoot.setAttribute('transform', `translate(${STATE.view.x},${STATE.view.y}) scale(${STATE.view.k})`); }
function fmtUsd(v) { if (v == null) return '—'; if (v >= 1e9) return '$' + (v / 1e9).toFixed(1) + 'B'; if (v >= 1e6) return '$' + (v / 1e6).toFixed(1) + 'M'; if (v >= 1e3) return '$' + (v / 1e3).toFixed(0) + 'k'; return '$' + v; }

function chrome() {
  const lang = STATE.lang;
  document.getElementById('t-ro').textContent = tr('ro');
  const mtro = document.getElementById('mt-ro'); if (mtro) mtro.textContent = tr('ro');
  document.getElementById('resetbtn').textContent = tr('reset');
  document.getElementById('langbtn').textContent = lang === 'ru' ? 'EN' : 'RU';
  const ml = document.getElementById('mlangbtn'); if (ml) ml.textContent = lang === 'ru' ? 'EN' : 'RU';
  document.getElementById('cr-here').textContent = vlabel(STATE.viewId);
  // sidebar nav groups
  const nav = document.getElementById('nav'); nav.replaceChildren();
  const dn = (STATE.rm && STATE.rm.decisions && STATE.rm.decisions.items && STATE.rm.decisions.items.length) || 0;
  let curGrp = null;
  VIEWS.forEach(v => {
    if (v.grp !== curGrp) { curGrp = v.grp; nav.append(H('div', { class: 'nav-grp' }, vlabel(v.grp))); }
    const b = H('button', { class: 'nav-item' + (v.id === STATE.viewId ? ' on' : ''), onclick: () => applyView(v.id) }, H('span', { class: 'ni' }, v.icon), H('span', {}, vlabel(v.id)));
    if ((v.id === 'decisions' || v.id === 'home') && dn) b.append(H('span', { class: 'nb warn' }, String(dn)));
    nav.append(b);
  });
  const disp = STATE.rm && STATE.rm.system && STATE.rm.system.dispatch;
  document.getElementById('sb-status').textContent = (lang === 'ru' ? 'только чтение' : 'read-only') + (disp && !disp.open ? (lang === 'ru' ? ' · диспетч закрыта' : ' · dispatch closed') : '');
  // chips + directory (graph views only)
  const chipHost = document.getElementById('chips'); chipHost.replaceChildren();
  const dir = document.getElementById('directory'); dir.replaceChildren();
  if (GRAPH_VIEWS.has(STATE.viewId) && STATE.model) {
    document.getElementById('t-legend').textContent = tr('legend');
    ['__all__', ...DOMAIN_ORDER.filter(d => STATE.model.nodes.some(n => n.domain === d))].forEach(d => {
      const on = d === '__all__' ? !STATE.focusDomain : STATE.focusDomain === d;
      chipHost.append(H('button', { class: 'chip' + (on ? ' on' : ''), onclick: () => { STATE.focusDomain = d === '__all__' ? null : d; STATE.focus = d === '__all__' ? null : DOMAIN_HUB[d]; relayout(); applyFocus(); renderPanel(d === '__all__' ? null : nodeById[DOMAIN_HUB[d]]); chrome(); } }, d === '__all__' ? tr('all') : dname(d)));
    });
    dir.append(H('div', { class: 'dhead' }, tr('dir')));
    DOMAIN_ORDER.filter(d => STATE.model.nodes.some(n => n.domain === d)).forEach(d => {
      const cnt = STATE.model.nodes.filter(n => n.domain === d && !n.hub).length;
      dir.append(H('div', { class: 'drow', onclick: () => applyView(d === 'factory' ? 'research' : d) }, H('span', { class: 'dmark', style: `background:${DOMAIN_ACCENT[d]}` }), H('span', { class: 'dnm' }, dname(d)), H('span', { class: 'dct' }, String(cnt))));
    });
    dir.append(H('div', { class: 'dhead', style: 'margin-top:14px' }, tr('tracks')));
    ['MARKET', 'STUDIO', 'PAPER', 'UNKNOWN'].forEach(t2 => dir.append(H('div', { class: 'drow' }, H('span', { class: 'dmark', style: `background:${TRACK[t2]}` }), H('span', { class: 'dnm' }, tkname(t2)))));
  }
  // bottom nav (mobile)
  const bn = document.getElementById('bottomnav'); bn.replaceChildren();
  BOTTOM.forEach(id => {
    const v = VIEWS.find(x => x.id === id);
    const on = STATE.viewId === id || (id === 'system' && STATE.mode === 'system');
    const central = id === 'voice';
    const b = H('button', { class: (on ? 'on' : '') + (central ? ' bn-voice' : ''), onclick: () => applyView(id) },
      H('span', { class: 'bi' }, v.icon), H('span', {}, vlabel(id)));
    if (id === 'home' && dn) b.append(H('span', { class: 'nb' }, String(dn)));
    bn.append(b);
  });
}

function boot() {
  const setLang = () => { STATE.lang = STATE.lang === 'ru' ? 'en' : 'ru'; localStorage.setItem('sos.lang', STATE.lang); document.documentElement.lang = STATE.lang; applyView(); };
  document.getElementById('langbtn').addEventListener('click', setLang);
  const ml = document.getElementById('mlangbtn'); if (ml) ml.addEventListener('click', setLang);
  document.getElementById('resetbtn').addEventListener('click', () => { STATE.view = { x: 0, y: 0, k: 1 }; applyView(); });
  const burger = document.getElementById('burger'); if (burger) burger.addEventListener('click', () => document.body.classList.toggle('drawer'));
  const scrim = document.getElementById('scrim'); if (scrim) scrim.addEventListener('click', () => document.body.classList.remove('drawer'));
  applyView(qs.get('view') || 'home');
  // ⌘K / Ctrl-K global command palette (navigation + real-object search)
  window.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      const views = VIEWS.filter(v => v.grp === 'os' || v.grp === 'defi').map(v => ({ id: v.id, label: vlabel(v.id) }));
      const open = () => openCommand({ lang: STATE.lang, nav: navBridge(), views, index: STATE.searchIndex });
      if (STATE.searchIndex) open();
      else fetch('./search_index.json').then(r => r.json()).then(ix => { STATE.searchIndex = ix; open(); }).catch(open);
    }
  });
  window.addEventListener('resize', () => { STATE.view = { x: 0, y: 0, k: 1 }; applyView(); });
  if (qs.get('ovcheck')) setTimeout(() => { const de = document.documentElement; console.log('OVCHECK sw=' + de.scrollWidth + ' iw=' + window.innerWidth + ' ok=' + (de.scrollWidth <= window.innerWidth)); }, 700);
}
load().then(boot);
