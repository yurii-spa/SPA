// Studio OS Core screens — PROJECT HOME (Context Pack) + MEMORY/SEARCH. Read-only projections (ADR-495).
const H = (t, a = {}, ...k) => {
  const n = document.createElement(t);
  for (const [key, v] of Object.entries(a)) {
    if (v == null) continue;
    if (key === 'class') n.className = v;
    else if (key.startsWith('on')) n.addEventListener(key.slice(2), v);
    else n.setAttribute(key, v);
  }
  for (const c of k) if (c != null) n.append(c.nodeType ? c : document.createTextNode(c));
  return n;
};
const L = (lang, ru, en) => (lang === 'ru' ? ru : en);
const val = (f) => (f && typeof f === 'object' && 'value' in f) ? f.value : f;

function kv(k, v, prov, accent) {
  const row = H('div', { class: 'pc-kv' },
    H('div', { class: 'pc-k' }, k),
    H('div', { class: 'pc-v' + (accent ? ' acc' : '') }, v == null ? '—' : (typeof v === 'object' ? JSON.stringify(v) : String(v))));
  if (prov) row.append(H('div', { class: 'pc-prov' }, prov));
  return row;
}

// ── PROJECT HOME (Context Pack) — understand the project in ≤30s ──────────────────────────
export function renderProjects(mount, ctx, projects, lang, nav, repo) {
  mount.replaceChildren();
  const wrap = H('div', { class: 'surf' });
  const projList = (projects && projects.projects) || [];
  // project chips
  const chips = H('div', { class: 'surf-chips' });
  projList.forEach(p => chips.append(H('span', { class: 'surf-chip' + (p.project_id === 'earn-defi-product' ? ' on' : '') }, p.name)));
  wrap.append(H('div', { class: 'surf-hbar' }, H('div', { class: 'surf-h' }, L(lang, 'ПРОЕКТЫ', 'PROJECTS')), chips));

  if (!ctx || !ctx.purpose) { mount.append(wrap.appendChild(H('div', { class: 'surf-empty' }, L(lang, 'КОНТЕКСТ НЕДОСТУПЕН', 'CONTEXT NOT AVAILABLE'))) && wrap); return; }

  const proj = val(ctx.project) || {};
  wrap.append(H('div', { class: 'pc-hero' },
    H('div', { class: 'pc-title' }, proj.name || 'Earn DeFi', H('span', { class: 'pc-status' }, proj.status || '')),
    H('div', { class: 'pc-purpose' }, val(ctx.purpose)),
    H('div', { class: 'pc-next' }, H('span', { class: 'pc-next-l' }, L(lang, 'СЛЕДУЮЩИЙ ШАГ', 'NEXT')), val(ctx.next_recommended_work))));

  // two columns: state (left) / governance (right)
  const grid = H('div', { class: 'pc-grid' });
  const left = H('div', {}), right = H('div', {});

  // WORK
  const w = val(ctx.work) || {};
  const card = (title) => { const c = H('div', { class: 'pc-card' }, H('h4', {}, title)); return c; };
  const wc = card(L(lang, 'РАБОТА', 'WORK'));
  [['active', 'running'], ['owner_wait', 'needs owner'], ['blocked', 'blocked'], ['review', 'review'], ['failed', 'failed'], ['done_recent', 'done']].forEach(([k, lbl]) =>
    wc.append(H('div', { class: 'pc-stat' + ((w[k] && (k === 'blocked' || k === 'failed' || k === 'owner_wait')) ? ' warn' : '') }, H('span', {}, lbl), H('b', {}, String(w[k] ?? 0)))));
  wc.append(H('div', { class: 'pc-prov' }, ctx.work.provenance));
  left.append(wc);

  // OWNER WAITING
  const ow = val(ctx.owner_decisions_waiting) || [];
  const owc = card(L(lang, 'ЖДЁТ ВЛАДЕЛЬЦА', 'NEEDS OWNER') + ' · ' + ow.length);
  if (!ow.length) owc.append(H('div', { class: 'pc-empty' }, '—'));
  ow.forEach(d => owc.append(H('div', { class: 'pc-row' }, d.title)));
  left.append(owc);

  // RECENT
  const act = val(ctx.recent_activity) || [];
  const ac = card(L(lang, 'НЕДАВНЕЕ', 'RECENT'));
  (act.length ? act : ['—']).forEach(a => ac.append(H('div', { class: 'pc-row dim' }, typeof a === 'string' ? a : JSON.stringify(a))));
  left.append(ac);

  // BOUNDARIES + DO NOT REDESIGN
  const bc = card(L(lang, 'ГРАНИЦЫ', 'BOUNDARIES'));
  bc.append(H('div', { class: 'pc-row' }, val(ctx.boundaries)));
  bc.append(H('div', { class: 'pc-prov' }, ctx.boundaries.provenance));
  right.append(bc);

  const dnr = val(ctx.do_not_redesign) || [];
  const dc = card(L(lang, 'НЕ ПЕРЕДЕЛЫВАТЬ', 'DO NOT REDESIGN'));
  dnr.forEach(x => dc.append(H('div', { class: 'pc-chip-row' }, '⛔ ' + x)));
  right.append(dc);

  // DECISIONS
  const dec = val(ctx.accepted_decisions) || [];
  const drafts = val(ctx.proposed_decisions) || [];
  const dcard = card(L(lang, 'РЕШЕНИЯ', 'DECISIONS'));
  if (drafts.length) dcard.append(H('div', { class: 'pc-row warn' }, L(lang, 'Черновиков (PROPOSED): ', 'Drafts (PROPOSED): ') + drafts.length));
  dec.slice(0, 5).forEach(d => dcard.append(H('div', { class: 'pc-row' }, H('button', { class: 'pc-link', onclick: () => nav && nav.go && nav.go('decisions') }, d.id), ' ' + (d.summary || '').slice(0, 60))));
  dcard.append(H('div', { class: 'pc-prov' }, ctx.accepted_decisions.provenance));
  right.append(dcard);

  // RELEASES + HEALTH
  const rc = card(L(lang, 'РЕЛИЗЫ / ЗДОРОВЬЕ', 'RELEASES / HEALTH'));
  rc.append(kv('GoLive', (val(ctx.releases) || {}).golive, ctx.releases.provenance));
  rc.append(kv(L(lang, 'диспетчер', 'dispatch'), (val(ctx.runtime_health) || {}).dispatch, null));
  rc.append(kv('risk-alerts', (val(ctx.risks) || {}).risk_alerts, null));
  right.append(rc);

  // LAST HANDOFF
  const lh = val(ctx.last_handoff);
  const hc = card(L(lang, 'ПОСЛЕДНИЙ ХЕНДОФФ', 'LAST HANDOFF'));
  hc.append(H('div', { class: 'pc-row dim' }, lh ? (lh.done || lh.journal || JSON.stringify(lh)).toString().slice(0, 120) : '—'));
  hc.append(H('div', { class: 'pc-prov' }, ctx.last_handoff.provenance));
  right.append(hc);

  // CODE SYNC (ADR-494) — candidate / canonical / production
  if (repo && repo.candidate) {
    const sc = card(L(lang, 'СИНХРОНИЗАЦИЯ КОДА (ADR-494)', 'CODE SYNC (ADR-494)'));
    const st = repo.candidate.state_vs_canonical;
    const warn = st !== 'IN_SYNC' || repo.production.state_vs_canonical !== 'IN_SYNC';
    sc.append(kv(L(lang, 'КАНОН', 'CANONICAL'), (repo.canonical.sha_short || '—') + ' (origin/main)'));
    sc.append(kv(L(lang, 'КАНДИДАТ', 'CANDIDATE'), (repo.candidate.sha_short || '—') + ' · ' + st + ` (+${repo.candidate.ahead ?? '?'}/-${repo.candidate.behind ?? '?'})`, null, warn));
    sc.append(kv(L(lang, 'ПРОДАКШН', 'PRODUCTION'), (repo.production.sha_short || '—') + ' · ' + repo.production.state_vs_canonical));
    sc.append(H('div', { class: 'pc-row' + (repo.deployment_required ? ' warn' : '') }, (repo.deployment_required ? '⚠ ' : '✓ ') + L(lang, 'деплой требуется: ', 'deployment required: ') + (repo.deployment_required ? 'ДА' : 'нет')));
    sc.append(H('div', { class: 'pc-prov' }, repo.promotion_path));
    right.append(sc);
  }

  grid.append(left, right);
  wrap.append(grid);
  wrap.append(H('div', { class: 'surf-foot' }, H('span', { class: 'surf-prov' }, ctx.generated_note + ' · ' + (ctx.generated_at || ''))));
  mount.append(wrap);
}

// ── WORK — real states from the mission ledger (read_model.work); task drill-down ─────────
const ZONE_ORDER = ['owner_wait', 'blocked', 'failed', 'running', 'review', 'planned', 'queued', 'done'];
const ZONE_LABEL = { owner_wait: ['ЖДЁТ ВЛАДЕЛЬЦА', 'WAITING OWNER'], blocked: ['ЗАБЛОКИРОВАНО', 'BLOCKED'], failed: ['УПАЛО', 'FAILED'], running: ['В РАБОТЕ', 'RUNNING'], review: ['НА РЕВЬЮ', 'REVIEW'], planned: ['ЗАПЛАНИРОВАНО', 'PLANNED'], queued: ['В ОЧЕРЕДИ', 'QUEUED'], done: ['ЗАВЕРШЕНО', 'RECENTLY COMPLETED'] };
const ZONE_COLOR = { owner_wait: '#d6a94a', blocked: '#d68b5a', failed: '#d66a6a', running: '#7aa2d8', review: '#5fb8ac', done: '#5aa17a', planned: '#6b7690', queued: '#6b7690' };
let _openTask = null;
let _taskLinks = {};
export function renderWork(mount, rm, lang, nav, links) {
  _taskLinks = (links && links.links) || {};
  mount.replaceChildren();
  const work = (rm && rm.work) || [];
  const wrap = H('div', { class: 'surf' });
  wrap.append(H('div', { class: 'surf-hbar' }, H('div', { class: 'surf-h' }, L(lang, 'РАБОТА', 'WORK')), H('span', { class: 'surf-count' }, String(work.length))));
  const byZone = {};
  work.forEach(w => { const z = w.ui_state || w.zone; (byZone[z] = byZone[z] || []).push(w); });
  ZONE_ORDER.forEach(z => {
    const items = byZone[z] || [];
    if (!items.length) return;
    const col = ZONE_COLOR[z] || '#6b7690';
    wrap.append(H('div', { class: 'wk-zone' }, H('span', { class: 'wk-dot', style: `background:${col}` }), H('span', { class: 'wk-zl' }, (ZONE_LABEL[z] ? ZONE_LABEL[z][lang === 'ru' ? 0 : 1] : z)), H('span', { class: 'wk-zc' }, String(items.length))));
    items.slice(0, z === 'done' ? 8 : 40).forEach(w => {
      wrap.append(H('button', { class: 'wk-row', onclick: () => renderTaskDetail(w, lang) },
        H('span', { class: 'wk-state', style: `color:${col};border-color:${col}` }, w.ui_state || w.state),
        H('span', { class: 'wk-title' }, w.title || w.request_summary || w.id)));
    });
  });
  if (!work.length) wrap.append(H('div', { class: 'surf-empty' }, L(lang, 'НЕТ РАБОТЫ В ЛЕДЖЕРЕ', 'NO WORK IN LEDGER')));
  wrap.append(H('div', { class: 'surf-foot' }, H('span', { class: 'surf-prov' }, L(lang, 'источник: read_model.json ← mission-state ledger', 'source: read_model.json ← mission-state ledger'))));
  mount.append(wrap);
}
function tdRow(k, v, missing) {
  return H('div', { class: 'prow' }, H('span', { class: 'pk' }, k), H('span', { class: 'pv' + (missing ? ' warn' : '') }, v == null || v === '' ? (missing || 'MISSING') : String(v)));
}
function renderTaskDetail(w, lang) {
  const host = window.innerWidth <= 860 ? document.getElementById('sheet') : document.getElementById('panel');
  _openTask = w;
  const ru = lang === 'ru';
  const wrap = H('div', {});
  wrap.append(H('div', { class: 'phead' }, H('span', { class: 'pmark' }),
    H('div', { class: 'ptitle' }, H('strong', {}, (w.title || w.id).slice(0, 80)), H('span', { class: 'psub' }, 'WORK ITEM')),
    H('button', { class: 'px', onclick: () => { host.classList.remove('open'); host.replaceChildren(); } }, '×')));
  wrap.append(H('div', { class: 'psec' }, ru ? 'ПОЧЕМУ ЭТА ЗАДАЧА' : 'WHY THIS TASK'));
  wrap.append(H('div', { class: 'prov', style: 'color:var(--ink2)' }, w.request_summary || w.reason_code || (ru ? 'нет описания' : 'no summary')));
  wrap.append(H('div', { class: 'psec' }, ru ? 'СОСТОЯНИЕ' : 'STATE'));
  wrap.append(tdRow(ru ? 'СТАТУС' : 'STATUS', w.state));
  wrap.append(tdRow(ru ? 'UI-СОСТОЯНИЕ' : 'UI STATE', w.ui_state));
  wrap.append(tdRow(ru ? 'ЗОНА (ПРАВА)' : 'PERMISSION ZONE', w.zone));
  wrap.append(tdRow(ru ? 'ПРИЧИНА' : 'REASON', w.reason_code));
  wrap.append(tdRow(ru ? 'МИССИЯ' : 'MISSION', w.mission_id));
  const lk = _taskLinks[w.id] || _taskLinks[w.work_item_id] || {};
  const org = lk._origins || {};
  const has = Object.keys(lk).some(k => k !== 'provenance' && k !== '_origins');
  wrap.append(H('div', { class: 'psec' }, (ru ? 'СВЯЗИ' : 'LINKS') + (has ? '' : (ru ? ' (нет источника → MISSING)' : ' (no source → MISSING)'))));
  const arr = (v) => Array.isArray(v) ? v.join(', ') : v;
  // link row with origin class (EXPLICIT/DERIVED/HEURISTIC/UNKNOWN — ADR-497): heuristic never shown as fact
  const lr = (label, field, missing) => {
    const v = lk[field]; const o = org[field];
    const row = H('div', { class: 'prow' }, H('span', { class: 'pk' }, label),
      H('span', { class: 'pv' + (v == null ? ' warn' : '') }, v == null ? (missing || 'MISSING') : String(arr(v))));
    if (v != null && o) row.append(H('span', { class: 'lk-org lk-' + o }, o));
    return row;
  };
  wrap.append(lr(ru ? 'ПРОЕКТ' : 'PROJECT', 'project_id', ru ? 'НЕ ПРИВЯЗАН' : 'NOT LINKED'));
  wrap.append(lr(ru ? 'КРИТЕРИЙ ПРИЁМКИ' : 'ACCEPTANCE', 'acceptance_criteria', 'MISSING'));
  wrap.append(lr(ru ? 'РЕШЕНИЕ' : 'DECISION', 'decision_refs', 'MISSING'));
  wrap.append(lr(ru ? 'ИССЛЕДОВАНИЕ' : 'RESEARCH', 'research_refs', 'MISSING'));
  wrap.append(lr(ru ? 'ДОКАЗАТЕЛЬСТВА' : 'EVIDENCE', 'evidence_refs', 'MISSING'));
  wrap.append(lr(ru ? 'КОММИТ' : 'COMMIT', 'implementation_commit', 'MISSING'));
  wrap.append(lr(ru ? 'ИСХОД' : 'OUTCOME', 'outcome', 'MISSING'));
  wrap.append(lr(ru ? 'ХЕНДОФФ' : 'HANDOFF', 'handoff_ref', 'MISSING'));
  wrap.append(lr(ru ? 'РЕЛИЗ' : 'RELEASE', 'release_ref', 'MISSING'));
  wrap.append(H('div', { class: 'prov' }, (ru ? 'ИСТОЧНИК · ' : 'SOURCE · ') + 'read_model.json#work[' + (w.id || '') + '] ← mission ledger'
    + (lk.provenance ? ' · ' + (ru ? 'связи: ' : 'links: ') + lk.provenance : '')));
  host.replaceChildren(wrap); host.classList.add('open');
}

// ── RESEARCH — relationship model (research → decision), ORPHAN honest ─────────────────────
export function renderResearch(mount, model, lang) {
  mount.replaceChildren();
  const wrap = H('div', { class: 'surf' });
  if (!model || !model.present) { mount.append(wrap.appendChild(H('div', { class: 'surf-empty' }, L(lang, 'ИССЛЕДОВАНИЯ НЕДОСТУПНЫ', 'RESEARCH NOT AVAILABLE'))) && wrap); return; }
  const bd = model.orphan_breakdown || {};
  wrap.append(H('div', { class: 'surf-hbar' }, H('div', { class: 'surf-h' }, L(lang, 'ИССЛЕДОВАНИЯ → РЕШЕНИЯ', 'RESEARCH → DECISIONS')),
    H('span', { class: 'surf-count' }, `${model.linked}✓ / ${model.orphan}⊘ / ${model.total}`)));
  wrap.append(H('div', { class: 'rs-chain' }, ['RESEARCH', 'EVIDENCE', 'DECISION', 'TASK', 'RESULT'].map((s, i) => H('span', {}, (i ? ' → ' : '') + s))));
  // orphan breakdown legend (why unlinked — goal is understanding, not 100% linkage)
  wrap.append(H('div', { class: 'rs-legend' }, L(lang, 'Почему не связано: ', 'Why unlinked: ')
    + Object.entries(bd).map(([k, v]) => `${k} ${v}`).join(' · ')));
  const OC = { LIKELY_STANDALONE: '#5aa17a', LIKELY_MISSING_LINK: '#d6a94a', OBSOLETE: '#6b7690', UNKNOWN: '#d66a6a' };
  (model.items || []).forEach(it => {
    const linked = it.status === 'LINKED';
    const oc = it.orphan_class;
    const conf = it.orphan_confidence;
    const card = H('div', { class: 'rs-card' + (linked ? '' : ' orphan') },
      H('div', { class: 'rs-top' }, H('span', { class: 'rs-badge ' + (linked ? 'ok' : 'orphan') }, linked ? 'LINKED' : oc),
        !linked && conf ? H('span', { class: 'rs-conf' }, conf) : null,
        H('span', { class: 'rs-title', style: linked ? '' : `border-left:2px solid ${OC[oc] || '#6b7690'};padding-left:8px` }, it.title), it.date ? H('span', { class: 'rs-date' }, it.date) : null),
      H('div', { class: 'rs-meta' },
        H('span', { class: it.evidence && it.evidence.cites_standard ? 'rs-ev ok' : 'rs-ev' }, (it.evidence && it.evidence.cites_standard) ? L(lang, 'цитирует стандарт эвиденса', 'cites evidence standard') : L(lang, 'без эвиденс-ссылки', 'no evidence ref')),
        linked ? H('span', { class: 'rs-supports' }, L(lang, 'поддерживает: ', 'supports: ') + it.supports_decisions.slice(0, 3).join(', ')) : H('span', { class: 'rs-orphan', title: it.orphan_reason || '' }, it.orphan_reason || L(lang, 'не связано', 'unlinked')),
        H('span', { class: 'rs-ref' }, it.ref)));
    wrap.append(card);
  });
  wrap.append(H('div', { class: 'surf-foot' }, H('span', { class: 'surf-prov' }, model.note)));
  mount.append(wrap);
}

// ── MEMORY / GLOBAL SEARCH — deterministic, over real indexed objects ─────────────────────
const TYPE_COLOR = { project: '#7aa2d8', decision: '#5fb8ac', 'decision-draft': '#d6a94a', task: '#d6a94a', research: '#8f7bff', release: '#5aa17a', report: '#7aa2d8', handoff: '#6b7690' };
// authority order: canon outranks a derived report so an old report never looks equal to an accepted ADR
const AUTH_RANK = { CANONICAL: 6, ACCEPTED_DECISION: 5, CANONICAL_WORK: 4, CANONICAL_RESEARCH: 4, HANDOFF: 3, PROPOSED_DECISION: 2, DERIVED_REPORT: 1 };
const AUTH_COLOR = { CANONICAL: '#7aa2d8', ACCEPTED_DECISION: '#5fb8ac', CANONICAL_WORK: '#5fb8ac', CANONICAL_RESEARCH: '#8f7bff', HANDOFF: '#6b7690', PROPOSED_DECISION: '#d6a94a', DERIVED_REPORT: '#8a93ac' };
export function renderSearch(mount, index, lang) {
  mount.replaceChildren();
  const items = (index && index.items) || [];
  const wrap = H('div', { class: 'surf' });
  wrap.append(H('div', { class: 'surf-hbar' }, H('div', { class: 'surf-h' }, L(lang, 'ПАМЯТЬ / ПОИСК', 'MEMORY / SEARCH')),
    H('span', { class: 'surf-count' }, String(items.length))));
  const input = H('input', { class: 'voice-text', type: 'text', placeholder: L(lang, 'Найти: «Position Passport», «kill switch», «Aave»…', 'Search: "Position Passport", "kill switch", "Aave"…') });
  const results = H('div', { class: 'srch-results' });
  wrap.append(input, results);

  const run = () => {
    const q = input.value.trim().toLowerCase();
    results.replaceChildren();
    if (!q) return;
    const terms = q.split(/\s+/).filter(Boolean);
    const scored = [];
    for (const it of items) {
      const hay = ((it.title || '') + ' ' + (it.text || '') + ' ' + (it.kw || '')).toLowerCase();
      if (terms.every(t => hay.includes(t))) {
        scored.push([terms.reduce((s, t) => s + hay.split(t).length - 1, 0), it]);
      }
    }
    // rank by authority first (canon over report), then match score
    scored.sort((a, b) => (AUTH_RANK[b[1].authority] || 0) - (AUTH_RANK[a[1].authority] || 0) || b[0] - a[0]);
    if (!scored.length) { results.append(H('div', { class: 'pc-empty' }, L(lang, 'Ничего не найдено', 'No results'))); return; }
    scored.slice(0, 30).forEach(([sc, it]) => {
      const ac = AUTH_COLOR[it.authority] || '#6b7690';
      results.append(H('div', { class: 'srch-row' },
        H('span', { class: 'srch-auth', style: `color:${ac};border-color:${ac}`, title: 'authority' }, (it.authority || 'DERIVED').replace('_', ' ')),
        H('span', { class: 'srch-type', style: `color:${TYPE_COLOR[it.type] || '#6b7690'}` }, it.type),
        H('span', { class: 'srch-title' }, it.title),
        H('span', { class: 'srch-ref' }, it.ref)));
    });
    results.append(H('div', { class: 'pc-prov' }, L(lang, scored.length + ' совпадений · ранжировано по авторитету (канон › отчёт) · детерминированный локальный индекс', scored.length + ' matches · ranked by authority (canon › report) · deterministic local index')));
  };
  input.addEventListener('input', run);
  mount.append(wrap);
  setTimeout(() => input.focus(), 50);
}

// ── GLOBAL COMMAND PALETTE (⌘K) — navigation + search over real objects, no fake commands ──
export function openCommand(ctx) {
  const { lang, nav, views, index } = ctx;
  let ov = document.getElementById('cmdk');
  if (ov) ov.remove();
  ov = H('div', { id: 'cmdk', class: 'cmdk' });
  const box = H('div', { class: 'cmdk-box' });
  const input = H('input', { class: 'cmdk-input', type: 'text', placeholder: L(lang, 'Перейти или найти… (проекты, работа, решения, исследования, память)', 'Go to or search… (projects, work, decisions, research, memory)') });
  const list = H('div', { class: 'cmdk-list' });
  box.append(input, list); ov.append(box);
  const close = () => ov.remove();
  ov.addEventListener('click', (e) => { if (e.target === ov) close(); });
  const navCmds = (views || []).map(v => ({ kind: 'nav', id: v.id, label: v.label, view: v.id }));
  const render = () => {
    const q = input.value.trim().toLowerCase();
    list.replaceChildren();
    const rows = [];
    // navigation commands (always, filtered)
    navCmds.filter(c => !q || c.label.toLowerCase().includes(q) || c.id.includes(q)).slice(0, 8).forEach(c => rows.push(c));
    // object results from the search index (only when typing)
    if (q && index && index.items) {
      const terms = q.split(/\s+/).filter(Boolean);
      const hits = index.items.filter(it => terms.every(t => ((it.title || '') + ' ' + (it.kw || '')).toLowerCase().includes(t)))
        .sort((a, b) => (({ CANONICAL: 6, ACCEPTED_DECISION: 5, CANONICAL_WORK: 4, CANONICAL_RESEARCH: 4, HANDOFF: 3, PROPOSED_DECISION: 2, DERIVED_REPORT: 1 }[b.authority] || 0) - ({ CANONICAL: 6, ACCEPTED_DECISION: 5, CANONICAL_WORK: 4, CANONICAL_RESEARCH: 4, HANDOFF: 3, PROPOSED_DECISION: 2, DERIVED_REPORT: 1 }[a.authority] || 0)))
        .slice(0, 8);
      hits.forEach(h => rows.push({ kind: 'obj', label: h.title, sub: (h.authority || '') + ' · ' + h.ref, view: 'memory', q }));
    }
    rows.forEach((r, i) => {
      const row = H('div', { class: 'cmdk-row' + (i === 0 ? ' on' : ''), onclick: () => { pick(r); } },
        H('span', { class: 'cmdk-kind' }, r.kind === 'nav' ? '↦' : '⌕'),
        H('span', { class: 'cmdk-label' }, r.label),
        r.sub ? H('span', { class: 'cmdk-sub' }, r.sub) : null);
      list.append(row);
    });
    list._rows = rows;
  };
  const pick = (r) => { close(); if (r.view === 'memory' && r.q) { nav.go('memory'); setTimeout(() => { const si = document.querySelector('#memoryview .voice-text'); if (si) { si.value = r.q; si.dispatchEvent(new Event('input')); } }, 300); } else nav.go(r.view); };
  input.addEventListener('input', render);
  input.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); else if (e.key === 'Enter' && list._rows && list._rows[0]) pick(list._rows[0]); });
  document.body.append(ov); render(); setTimeout(() => input.focus(), 30);
}
