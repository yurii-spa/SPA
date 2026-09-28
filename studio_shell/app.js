// Studio OS Shell — v0 read-only app. Vanilla JS, no build step. Consumes read_model.json.
// Both modes (Mission Control + Studio View) render the SAME canonical-derived state.
import { makeT } from './i18n.js';

const STATE = { lang: localStorage.getItem('sos.lang') || 'ru', mode: localStorage.getItem('sos.mode') || 'mission',
  page: 'overview', model: null, t: null, reduceMotion: localStorage.getItem('sos.rm') === '1' };

const NAV = [
  ['overview', '◎'], ['work', '▤'], ['decisions', '◆'], ['agents', '◇'], ['system', '❖'],
];
const ZONES = ['owner', 'intake', 'engineering', 'review', 'blocked', 'reliability', 'memory'];
const STATUS_ORDER = ['owner_wait','running','review','queued','planned','blocked','failed','done'];

const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) n.setAttribute(k, v);
  }
  for (const kid of kids) { if (kid == null) continue; n.append(kid.nodeType ? kid : document.createTextNode(kid)); }
  return n;
};

async function loadModel() {
  try {
    const r = await fetch('./read_model.json?_=' + Date.now());
    if (!r.ok) throw new Error('HTTP ' + r.status);
    STATE.model = await r.json();
  } catch (e) {
    STATE.model = { __error: String(e) };
  }
}

function fresh(t, f) {
  if (!f) return null;
  const lab = t('fresh.' + (f.freshness || 'UNKNOWN'), f.freshness);
  return el('span', { class: 'fresh ' + (f.freshness || 'UNKNOWN'), title: f.updated_at || '' }, lab);
}
function statusBadge(t, ui) { return el('span', { class: 'badge-s s-' + ui }, t('status.' + ui, ui)); }
function zonePill(zone) {
  if (!zone) return null;
  const cls = zone === 'red' ? 'z-red' : zone === 'yellow' ? 'z-yellow' : zone === 'green' ? 'z-green' : 'z-yellow';
  return el('span', { class: 'zone-pill ' + cls }, zone);
}

// ---------------- Mission Control pages ----------------
function pageOverview(t, m) {
  const ov = m.overview || {}; const c = ov.counts || {};
  const wrap = el('div', {});
  wrap.append(el('h1', { class: 'page' }, t('overview.title')));
  wrap.append(el('div', { class: 'page-sub' }, m.generated_at ? t('common.updated') + ': ' + fmtTime(m.generated_at) : ''));
  const kpi = el('div', { class: 'grid g-kpi' });
  const cards = [
    ['owner', ov.owner_waiting || 0, 'warn'],
    ['running', c.running || 0, 'accent'],
    ['blocked', c.blocked || 0, ov.blocked ? 'warn' : ''],
    ['failed', c.failed || 0, ov.failed ? 'bad' : ''],
    ['done', c.done || 0, 'good'],
    ['missions', ov.missions_total || 0, ''],
  ];
  for (const [key, val, cls] of cards) {
    kpi.append(el('div', { class: 'card kpi ' + cls }, el('div', { class: 'v' }, String(val)),
      el('div', { class: 'l' }, t('overview.' + key))));
  }
  wrap.append(kpi);

  const two = el('div', { class: 'grid g-2', style: 'margin-top:14px' });
  // dispatch + golive
  const sys = m.system || {}; const disp = sys.dispatch || {};
  const c1 = el('div', { class: 'card' }, el('h3', {}, t('overview.dispatch')));
  c1.append(row(t('overview.dispatch'), el('span', { class: 'badge-s ' + (disp.open ? 's-running' : 's-owner_wait') },
    disp.open ? t('overview.dispatch.open') : t('overview.dispatch.closed'))));
  if (!disp.open && disp.reason) c1.append(el('div', { class: 'note' }, '⚠︎ ' + disp.reason));
  const gl = sys.golive;
  if (gl) {
    c1.append(row(t('overview.golive'), el('span', {}, (gl.passed ?? '—') + ' / ' + (gl.total ?? '—'))));
    c1.append(row(t('system.trackDays'), el('span', {}, String(gl.real_track_days ?? t('common.unknown')))));
    if (gl.freshness) c1.append(row(t('common.updated'), fresh(t, gl.freshness)));
  }
  two.append(c1);
  // activity
  const c2 = el('div', { class: 'card' }, el('h3', {}, t('overview.activity')));
  const acts = (m.activity || []);
  if (!acts.length) c2.append(el('div', { class: 'note' }, t('overview.emptyActivity')));
  else {
    const ul = el('ul', { class: 'list-clean activity' });
    for (const a of acts.slice(0, 8)) ul.append(el('li', {}, el('span', { class: 't' }, shortTime(a.ts)), el('span', {}, a.text)));
    c2.append(ul);
  }
  two.append(c2);
  wrap.append(two);
  return wrap;
}

function pageWork(t, m) {
  const wrap = el('div', {});
  wrap.append(el('h1', { class: 'page' }, t('work.title')));
  const work = m.work || [];
  const counts = {}; for (const w of work) counts[w.ui_state] = (counts[w.ui_state] || 0) + 1;
  const filters = el('div', { class: 'filters' });
  const mk = (key, label) => {
    const b = el('button', { class: STATE.workFilter === key || (!STATE.workFilter && key === 'all') ? 'active' : '',
      onclick: () => { STATE.workFilter = key; render(); } }, label + (key !== 'all' && counts[key] ? ' · ' + counts[key] : ''));
    return b;
  };
  filters.append(mk('all', t('work.filter.all') + ' · ' + work.length));
  for (const s of STATUS_ORDER) if (counts[s]) filters.append(mk(s, t('status.' + s)));
  wrap.append(filters);
  const list = el('div', { class: 'tasklist' });
  const shown = work.filter(w => !STATE.workFilter || STATE.workFilter === 'all' || w.ui_state === STATE.workFilter)
    .sort((a, b) => STATUS_ORDER.indexOf(a.ui_state) - STATUS_ORDER.indexOf(b.ui_state));
  if (!shown.length) list.append(el('div', { class: 'empty' }, t('work.empty')));
  for (const w of shown) {
    list.append(el('div', { class: 'task', onclick: () => openTask(w) },
      el('span', { class: 'tid' }, (w.work_item_id || '').replace('wi-', '').slice(0, 8)),
      el('span', { class: 'ttitle' }, w.title || w.id),
      el('span', { class: 'tright' }, w.permission_zone ? zonePill(w.permission_zone) : null, statusBadge(t, w.ui_state))));
  }
  wrap.append(list);
  return wrap;
}

function pageDecisions(t, m) {
  const wrap = el('div', {});
  wrap.append(el('h1', { class: 'page' }, t('decisions.title')));
  const d = (m.decisions && m.decisions.items) || [];
  if (!d.length) { wrap.append(el('div', { class: 'empty' }, t('decisions.empty'))); return wrap; }
  const list = el('div', { class: 'tasklist' });
  for (const it of d) {
    const card = el('div', { class: 'card' });
    card.append(el('div', { style: 'display:flex;gap:10px;align-items:flex-start' },
      zonePill('red'), el('div', { style: 'flex:1;font-weight:600' }, it.title)));
    card.append(el('div', { class: 'note' }, t('decisions.needsOwner')));
    if (it.card) card.append(el('div', { class: 'mono', style: 'margin-top:6px' }, t('decisions.card') + ': ' + it.card + '.md'));
    list.append(card);
  }
  wrap.append(list);
  wrap.append(el('div', { class: 'note', style: 'margin-top:14px' }, t('decisions.note')));
  return wrap;
}

function pageAgents(t, m) {
  const wrap = el('div', {}); wrap.append(el('h1', { class: 'page' }, t('agents.title')));
  const roles = (m.roles && m.roles.ai_roles) || [];
  const c = el('div', { class: 'card' }, el('h3', {}, t('agents.aiRoles')));
  for (const r of roles) {
    const writes = r.writes === false ? t('agents.writesNo') : (typeof r.writes === 'string' ? t('agents.writesIsolated') : String(r.writes));
    c.append(el('div', { class: 'row' }, el('span', { class: 'k' }, r.role),
      el('span', { class: 'val' }, el('span', { class: 'badge-s ' + (r.writes === false ? 's-done' : 's-owner_wait') }, writes),
        r.tools ? el('span', { class: 'mono', style: 'margin-left:8px' }, r.tools.join(', ')) : null)));
  }
  wrap.append(c);
  const fleet = m.roles && m.roles.fleet;
  if (fleet) {
    const f = el('div', { class: 'card', style: 'margin-top:14px' }, el('h3', {}, t('agents.fleet')));
    f.append(row(t('agents.loaded'), el('span', {}, (fleet.total_loaded ?? '—') + ' / ' + (fleet.total_known ?? '—'))));
    f.append(row(t('agents.problems'), el('span', {}, String(fleet.problem_count ?? t('common.unknown')))));
    if (fleet.freshness) f.append(row(t('common.updated'), fresh(t, fleet.freshness)));
    f.append(el('div', { class: 'note' }, t('agents.fleetNote')));
    wrap.append(f);
  }
  return wrap;
}

function pageSystem(t, m) {
  const wrap = el('div', {}); wrap.append(el('h1', { class: 'page' }, t('system.title')));
  const sys = m.system || {};
  const two = el('div', { class: 'grid g-2' });
  // dispatch
  const cd = el('div', { class: 'card' }, el('h3', {}, t('system.dispatch')));
  cd.append(row(t('overview.dispatch'), el('span', { class: 'badge-s ' + (sys.dispatch?.open ? 's-running' : 's-owner_wait') },
    sys.dispatch?.open ? t('overview.dispatch.open') : t('overview.dispatch.closed'))));
  if (sys.dispatch?.reason) cd.append(el('div', { class: 'note' }, sys.dispatch.reason));
  two.append(cd);
  // provider + candidate
  for (const [k, plane] of [['system.provider', sys.provider_plane], ['system.candidate', sys.candidate_plane]]) {
    if (!plane) continue;
    const c = el('div', { class: 'card' }, el('h3', {}, t(k)));
    const fa = plane.last_activity;
    c.append(row(t('system.lastActivity'), fa ? fresh(t, fa) : el('span', {}, t('common.unknown'))));
    c.append(el('div', { class: 'note' }, plane.note || t('system.privNote')));
    two.append(c);
  }
  // golive
  if (sys.golive) {
    const g = el('div', { class: 'card' }, el('h3', {}, t('system.golive')));
    g.append(row('ready', el('span', { class: 'badge-s ' + (sys.golive.ready ? 's-done' : 's-owner_wait') }, String(sys.golive.ready))));
    g.append(row(t('system.golive'), el('span', {}, (sys.golive.passed ?? '—') + ' / ' + (sys.golive.total ?? '—'))));
    (sys.golive.blockers || []).forEach(b => g.append(el('div', { class: 'note' }, '• ' + b)));
    two.append(g);
  }
  // health + capacity
  const h = el('div', { class: 'card' }, el('h3', {}, t('system.health')));
  const ra = sys.health?.risk_alerts;
  if (ra) { h.append(row(t('system.riskAlerts'), el('span', {}, String(ra.count ?? t('common.unknown'))))); if (ra.freshness) h.append(row(t('common.updated'), fresh(t, ra.freshness))); }
  const ah = sys.health?.agents;
  if (ah) h.append(row(t('system.health'), el('span', {}, `${ah.overall ?? '?'} (${ah.healthy ?? 0}/${ah.total ?? 0})`)));
  const cap = m.capacity;
  if (cap && cap.subscription_plan) {
    h.append(row(t('system.plan'), el('span', {}, cap.subscription_plan)));
    h.append(row(t('system.costCycle'), el('span', {}, cap.cost_per_cycle_usd != null ? '$' + cap.cost_per_cycle_usd : t('common.unknown'))));
  }
  two.append(h);
  wrap.append(two);
  return wrap;
}

// ---------------- Studio View ----------------
function studioView(t, m) {
  const wrap = el('div', { class: 'studio-wrap' });
  const head = el('div', { class: 'studio-head' },
    el('h1', { class: 'page', style: 'margin:0' }, t('studio.title')),
    el('label', { class: 'toggle' },
      (() => { const cb = el('input', { type: 'checkbox' }); cb.checked = STATE.reduceMotion;
        cb.addEventListener('change', () => { STATE.reduceMotion = cb.checked; localStorage.setItem('sos.rm', cb.checked ? '1' : '0'); applyMotion(); }); return cb; })(),
      t('studio.reduceMotion')));
  wrap.append(head);
  wrap.append(el('div', { class: 'studio-head' }, el('div', { class: 'legend' }, t('studio.legend'))));
  const work = m.work || [];
  const byZone = {}; ZONES.forEach(z => byZone[z] = []);
  for (const w of work) { const z = w.zone && byZone[w.zone] ? w.zone : 'intake'; byZone[z].push(w); }
  // owner zone also gets decisions
  const dec = (m.decisions && m.decisions.items) || [];
  const stage = el('div', { class: 'stage' });
  for (const z of ZONES) {
    const items = byZone[z];
    const extra = z === 'owner' ? dec.length : 0;
    const zc = el('div', { class: 'zone z-' + z });
    zc.append(el('div', { class: 'zh' }, el('span', { class: 'zn' }, t('studio.zone.' + z)),
      el('span', { class: 'zc' }, String(items.length + extra))));
    const ag = el('div', { class: 'agents' });
    for (const w of items) {
      ag.append(el('div', { class: 'agent st-' + w.ui_state, onclick: () => openTask(w) },
        el('span', { class: 'av ' + (w.ui_state === 'running' ? 'running' : '') }),
        el('span', { class: 'an' }, w.title || w.work_item_id)));
    }
    if (z === 'owner') for (const d of dec) ag.append(el('div', { class: 'agent st-owner_wait' },
      el('span', { class: 'av' }), el('span', { class: 'an' }, d.title)));
    if (!items.length && !extra) ag.append(el('div', { class: 'empty-z' }, t('studio.empty')));
    zc.append(ag); stage.append(zc);
  }
  wrap.append(stage);
  return wrap;
}

// ---------------- Task drawer (shared entity across modes) ----------------
function openTask(w) {
  const t = STATE.t;
  const scrim = document.getElementById('scrim');
  const dr = document.getElementById('drawer');
  const body = dr.querySelector('.db');
  dr.querySelector('.dtitle').textContent = w.title || w.work_item_id;
  body.innerHTML = '';
  const add = (k, v) => body.append(row(k, typeof v === 'string' || typeof v === 'number' ? el('span', {}, String(v)) : v));
  body.append(el('div', { class: 'mono', style: 'margin-bottom:10px' }, w.work_item_id));
  add(t('task.state'), statusBadge(t, w.ui_state));
  add(t('task.backendState'), el('span', { class: 'mono' }, w.state || t('common.unknown')));
  if (w.permission_zone) add(t('common.zone'), zonePill(w.permission_zone));
  add(t('task.zone'), t('studio.zone.' + w.zone, w.zone));
  if (w.mission_id) add(t('task.mission'), el('span', { class: 'mono' }, w.mission_id));
  if (w.reason_code) add(t('task.reason'), w.reason_code);
  if (w.request_summary) add(t('task.request'), w.request_summary);
  if (w.created_at) add(t('task.created'), fmtTime(w.created_at));
  if (w.history_len != null) add(t('task.history'), String(w.history_len));
  if (w.attempt != null) add(t('common.attempt'), String(w.attempt));
  if (w.source) body.append(el('div', { class: 'note', style: 'margin-top:12px' }, t('task.provenance') + ': ' + w.source));
  scrim.classList.add('open'); dr.classList.add('open');
}
function closeDrawer() { document.getElementById('scrim').classList.remove('open'); document.getElementById('drawer').classList.remove('open'); }

// ---------------- helpers ----------------
function row(k, valNode) { return el('div', { class: 'row' }, el('span', { class: 'k' }, k), el('span', { class: 'val' }, valNode)); }
function fmtTime(s) { try { return new Date(s).toLocaleString(STATE.lang === 'ru' ? 'ru-RU' : 'en-US'); } catch { return s; } }
function shortTime(s) { if (!s) return '—'; try { return new Date(s).toLocaleTimeString(STATE.lang === 'ru' ? 'ru-RU' : 'en-US', { hour: '2-digit', minute: '2-digit' }); } catch { return ''; } }
function applyMotion() { document.body.classList.toggle('reduce-motion', STATE.reduceMotion); }

// ---------------- render ----------------
function render() {
  const t = STATE.t = makeT(STATE.lang);
  const m = STATE.model || {};
  const app = document.getElementById('app');
  app.innerHTML = '';
  const decCount = (m.decisions && m.decisions.items && m.decisions.items.length) || 0;

  // sidebar (desktop)
  const side = el('aside', { class: 'sidebar' });
  side.append(el('div', { class: 'brand' }, el('div', { class: 'logo' }),
    el('div', {}, el('div', { class: 'name' }, t('app.title')), el('div', { class: 'sub' }, t('app.subtitle')))));
  side.append(modeSwitch(t));
  const nav = el('nav', { class: 'nav' });
  for (const [key, ico] of NAV) {
    const b = el('button', { class: STATE.mode === 'mission' && STATE.page === key ? 'active' : '',
      onclick: () => { STATE.mode = 'mission'; STATE.page = key; persist(); render(); } },
      el('span', { class: 'ico' }, ico), el('span', {}, t('nav.' + key)));
    if (key === 'decisions' && decCount) b.append(el('span', { class: 'badge' }, String(decCount)));
    nav.append(b);
  }
  const sb = el('button', { class: STATE.mode === 'studio' ? 'active' : '',
    onclick: () => { STATE.mode = 'studio'; persist(); render(); } }, el('span', { class: 'ico' }, '◊'), el('span', {}, t('nav.studio')));
  nav.append(sb);
  side.append(nav);
  side.append(el('div', { class: 'spacer' }));
  side.append(el('button', { class: 'langbtn', onclick: toggleLang }, t('lang.switch')));
  app.append(side);

  // main
  const main = el('div', { class: 'main' });
  main.append(mobitop(t, decCount));
  const disp = m.system && m.system.dispatch;
  const banner = el('div', { class: 'topbanner' + (disp && !disp.open ? ' closed' : '') },
    el('span', { class: 'dot' }), el('span', {}, t('banner.readonly')));
  if (disp && !disp.open) banner.append(el('span', {}, '· ' + t('banner.dispatchClosed')));
  main.append(banner);

  let view;
  if (m.__error) view = el('div', { class: 'content' }, el('div', { class: 'empty' }, t('common.notAvailable') + ': read_model.json — ' + m.__error));
  else if (STATE.mode === 'studio') view = studioView(t, m);
  else {
    const content = el('div', { class: 'content' });
    const pages = { overview: pageOverview, work: pageWork, decisions: pageDecisions, agents: pageAgents, system: pageSystem };
    content.append((pages[STATE.page] || pageOverview)(t, m));
    view = content;
  }
  main.append(view);
  main.append(bottomnav(t, decCount));
  app.append(main);
  applyMotion();
}

function modeSwitch(t) {
  return el('div', { class: 'modeswitch' },
    el('button', { class: STATE.mode === 'mission' ? 'active' : '', onclick: () => { STATE.mode = 'mission'; persist(); render(); } }, t('mode.mission')),
    el('button', { class: STATE.mode === 'studio' ? 'active' : '', onclick: () => { STATE.mode = 'studio'; persist(); render(); } }, t('mode.studio')));
}
function mobitop(t, decCount) {
  return el('div', { class: 'mobitop' }, el('div', { class: 'logo' }), el('div', { class: 'name' }, t('app.title')),
    modeSwitch(t), el('button', { class: 'langbtn', onclick: toggleLang }, t('lang.switch')));
}
function bottomnav(t, decCount) {
  const bn = el('div', { class: 'bottomnav' });
  for (const [key, ico] of NAV) {
    const b = el('button', { class: STATE.mode === 'mission' && STATE.page === key ? 'active' : '',
      onclick: () => { STATE.mode = 'mission'; STATE.page = key; persist(); render(); } },
      el('span', { class: 'ico' }, ico), el('span', {}, t('nav.' + key)));
    if (key === 'decisions' && decCount) b.append(el('span', { class: 'badge' }, String(decCount)));
    bn.append(b);
  }
  bn.append(el('button', { class: STATE.mode === 'studio' ? 'active' : '', onclick: () => { STATE.mode = 'studio'; persist(); render(); } },
    el('span', { class: 'ico' }, '◊'), el('span', {}, t('nav.studio'))));
  return bn;
}
function toggleLang() { STATE.lang = STATE.lang === 'ru' ? 'en' : 'ru'; localStorage.setItem('sos.lang', STATE.lang); document.documentElement.lang = STATE.lang; render(); }
function persist() { localStorage.setItem('sos.mode', STATE.mode); }

async function boot() {
  document.documentElement.lang = STATE.lang;
  document.getElementById('scrim').addEventListener('click', closeDrawer);
  document.getElementById('drawer').querySelector('.x').addEventListener('click', closeDrawer);
  await loadModel();
  render();
  // gentle refresh of the read model view every 30s (read-only)
  setInterval(async () => { await loadModel(); render(); }, 30000);
}
boot();
