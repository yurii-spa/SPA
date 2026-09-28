// Owner Remote surfaces — CAPITAL · STRATEGIES · VOICE (read-only; UI ≠ canonical truth).
// NEW_COMPONENT. No money path, no canonical writes from here. REAL/PAPER/SHADOW never confused.
// Voice is an INPUT interface to existing Studio OS capabilities: GREEN executes read-only/nav/draft;
// YELLOW drafts + owner-confirm (canonical write stays the owner-gated backend step); RED never executes.

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
const fmtUsd = (v) => {
  if (v == null) return '—';
  if (v >= 1e9) return '$' + (v / 1e9).toFixed(2) + 'B';
  if (v >= 1e6) return '$' + (v / 1e6).toFixed(2) + 'M';
  if (v >= 1e3) return '$' + Math.round(v).toLocaleString();
  return '$' + v;
};
const L = (lang, ru, en) => (lang === 'ru' ? ru : en);
const TRACK_COLOR = { REAL: '#5fb8ac', PAPER: '#d6a94a', SHADOW: '#8f7bff', UNKNOWN: '#6b7690' };
const TIER_COLOR = { T1: '#5fb8ac', T2: '#d6a94a', T3: '#d66a6a' };
const STATUS_COLOR = { active: '#5fb8ac', research: '#7aa2d8', advisory: '#d6a94a', blocked: '#d66a6a', retired: '#6b7690' };

// ── CAPITAL ────────────────────────────────────────────────────────────────────────────
export function renderCapital(mount, cap, lang, nav) {
  mount.replaceChildren();
  if (!cap || !cap.present) {
    mount.append(H('div', { class: 'surf-empty' }, L(lang, 'КАПИТАЛ НЕДОСТУПЕН', 'CAPITAL NOT AVAILABLE'),
      H('div', { class: 'surf-sub' }, (cap && cap.note) || 'current_positions.json')));
    return;
  }
  const track = cap.track || 'UNKNOWN';
  const acc = TRACK_COLOR[track] || '#6b7690';
  const wrap = H('div', { class: 'surf' });

  // hero — total + explicit track (PAPER never shown as REAL)
  wrap.append(H('div', { class: 'cap-hero' },
    H('div', { class: 'cap-track', style: `color:${acc};border-color:${acc}` }, track +
      (cap.execution_mode && track === 'PAPER' ? ' · ' + String(cap.execution_mode).toUpperCase().replace(/_/g, ' ') : '')),
    H('div', { class: 'cap-total' }, fmtUsd(cap.total_usd)),
    H('div', { class: 'cap-note' }, L(lang,
      'ВИРТУАЛЬНЫЙ капитал — не реальные деньги.',
      'VIRTUAL capital — not real money.'))));

  // REAL / PAPER / SHADOW — three separate columns, only the live one lit
  const tk = cap.tracks || {};
  const trk = H('div', { class: 'cap-tracks' });
  ['REAL', 'PAPER', 'SHADOW'].forEach(k => {
    const val = tk[k];
    const on = val != null;
    trk.append(H('div', { class: 'cap-tcell' + (on ? ' on' : ''), style: on ? `border-color:${TRACK_COLOR[k]}` : '' },
      H('div', { class: 'cap-tk', style: on ? `color:${TRACK_COLOR[k]}` : '' }, k),
      H('div', { class: 'cap-tv' }, on ? fmtUsd(val) : L(lang, 'НЕТ ДАННЫХ', 'NOT AVAIL.'))));
  });
  wrap.append(trk);

  // deployed vs cash bar
  const dep = cap.deployed_usd, cash = cap.cash_usd, tot = (dep || 0) + (cash || 0);
  if (tot > 0) {
    const pctDep = Math.round((dep / tot) * 100);
    wrap.append(H('div', { class: 'cap-bar' },
      H('div', { class: 'cap-barfill', style: `width:${pctDep}%` }),
      H('div', { class: 'cap-barlbl' },
        H('span', {}, L(lang, 'РАЗМЕЩЕНО', 'DEPLOYED') + ' ' + fmtUsd(dep)),
        H('span', {}, L(lang, 'СВОБОДНО', 'CASH') + ' ' + fmtUsd(cash)))));
  }
  if (cap.accrued_yield_usd != null)
    wrap.append(H('div', { class: 'cap-kv' }, H('span', {}, L(lang, 'НАКОПЛЕННЫЙ ДОХОД', 'ACCRUED YIELD')),
      H('b', {}, fmtUsd(cap.accrued_yield_usd))));

  // allocation by protocol
  wrap.append(H('div', { class: 'surf-h' }, L(lang, 'РАСКЛАДКА ПО ПРОТОКОЛАМ', 'ALLOCATION BY PROTOCOL')));
  const list = H('div', { class: 'alloc-list' });
  (cap.allocations || []).forEach(a => {
    const pct = cap.total_usd ? Math.round((a.usd / cap.total_usd) * 100) : null;
    const ev = a.apy_evidenced;
    const row = H('button', { class: 'alloc-row', onclick: () => nav.openEntity('protocol', a.protocol, a) },
      H('div', { class: 'alloc-main' },
        H('div', { class: 'alloc-nm' }, a.protocol, pct != null ? H('span', { class: 'alloc-pct' }, pct + '%') : null),
        H('div', { class: 'alloc-usd' }, fmtUsd(a.usd))),
      H('div', { class: 'alloc-meta' },
        a.apy_pct != null
          ? H('span', { class: 'alloc-apy' + (ev ? '' : ' warn') }, a.apy_pct + '% ' + (ev ? L(lang, 'ДОК.', 'EVID') : L(lang, 'СТАТИК', 'STATIC')))
          : H('span', { class: 'alloc-apy warn' }, L(lang, 'ДОХ. НЕИЗВ.', 'YIELD UNKNOWN')),
        H('span', { class: 'alloc-track', style: `color:${TRACK_COLOR[a.track] || '#6b7690'}` }, a.track)));
    list.append(row);
  });
  wrap.append(list);

  // policy + freshness footer
  const foot = H('div', { class: 'surf-foot' });
  if (cap.policy_version) foot.append(H('span', { class: 'surf-badge' },
    'RiskPolicy ' + cap.policy_version + (cap.policy_compliant ? ' ✓' : '')));
  foot.append(H('span', { class: 'surf-badge fr-' + (cap.freshness || 'UNKNOWN') }, L(lang, 'СВЕЖЕСТЬ', 'FRESHNESS') + ' ' + (cap.freshness || 'UNKNOWN')));
  foot.append(H('span', { class: 'surf-prov' }, cap.provenance));
  wrap.append(foot);
  mount.append(wrap);
}

// ── STRATEGIES ─────────────────────────────────────────────────────────────────────────
let _stratFilter = null;
export function renderStrategies(mount, strat, lang, nav) {
  mount.replaceChildren();
  if (!strat || !strat.present) {
    mount.append(H('div', { class: 'surf-empty' }, L(lang, 'СТРАТЕГИИ НЕДОСТУПНЫ', 'STRATEGIES NOT AVAILABLE'),
      H('div', { class: 'surf-sub' }, (strat && strat.note) || 'strategy_summary.json')));
    return;
  }
  const wrap = H('div', { class: 'surf' });
  const all = strat.strategies || [];
  const tiers = [...new Set(all.map(s => s.tier).filter(Boolean))].sort();

  wrap.append(H('div', { class: 'surf-hbar' },
    H('div', { class: 'surf-h' }, L(lang, 'КАТАЛОГ СТРАТЕГИЙ', 'STRATEGY CATALOGUE'),
      H('span', { class: 'surf-count' }, String(strat.total))),
    H('span', { class: 'surf-badge fr-' + (strat.freshness || 'UNKNOWN') }, strat.freshness || 'UNKNOWN')));

  // tier filter chips
  const chips = H('div', { class: 'surf-chips' });
  [['*', L(lang, 'ВСЕ', 'ALL')], ...tiers.map(t => [t, t])].forEach(([k, lbl]) => {
    const on = (_stratFilter || '*') === k;
    chips.append(H('button', { class: 'surf-chip' + (on ? ' on' : ''), onclick: () => { _stratFilter = k === '*' ? null : k; renderStrategies(mount, strat, lang, nav); } }, lbl));
  });
  wrap.append(chips);

  const cards = H('div', { class: 'strat-list' });
  all.filter(s => !_stratFilter || s.tier === _stratFilter).forEach(s => {
    const tc = TIER_COLOR[s.tier] || '#6b7690';
    const sc = STATUS_COLOR[(s.status || '').toLowerCase()] || '#6b7690';
    const apy = (s.apy_min != null && s.apy_max != null) ? `${s.apy_min}–${s.apy_max}%`
      : (s.apy_mid != null ? s.apy_mid + '%' : L(lang, 'ЦЕЛЬ НЕИЗВ.', 'TARGET UNKNOWN'));
    cards.append(H('button', { class: 'strat-card', onclick: () => nav.openEntity('strategy', s.id, s) },
      H('div', { class: 'strat-top' },
        H('span', { class: 'strat-tier', style: `color:${tc};border-color:${tc}` }, s.tier || '—'),
        H('span', { class: 'strat-status', style: `color:${sc}` }, (s.status || 'UNKNOWN').toUpperCase())),
      H('div', { class: 'strat-nm' }, s.name),
      H('div', { class: 'strat-meta' },
        H('span', {}, L(lang, 'ЦЕЛЬ', 'TARGET') + ' ' + apy),
        s.max_drawdown_pct != null ? H('span', { class: 'strat-dd' }, L(lang, 'ХВОСТ', 'TAIL') + ' −' + s.max_drawdown_pct + '%') : null,
        s.type ? H('span', { class: 'strat-type' }, s.type) : null)));
  });
  wrap.append(cards);
  wrap.append(H('div', { class: 'surf-foot' },
    H('span', { class: 'surf-badge' }, L(lang, 'СОВЕТАТЕЛЬНЫЙ (paper)', 'ADVISORY (paper)')),
    H('span', { class: 'surf-prov' }, strat.provenance)));
  mount.append(wrap);
}

// ── INVESTMENT SLICE (Aave vertical: opportunity→strategy→position→capital→risk→result→why) ──
const FSTAT = { AVAILABLE: '#5aa17a', DERIVABLE: '#7aa2d8', PARTIAL: '#d6a94a', MISSING: '#d66a6a', NOT_APPLICABLE: '#6b7690' };
function fval(f) {
  if (!f || typeof f !== 'object') return '—';
  const v = f.value;
  if (v == null) return f.note ? '—' : '—';
  if (Array.isArray(v)) return v.length ? (typeof v[0] === 'object' ? v.map(x => x.name || x.id || JSON.stringify(x)).join(', ') : v.join(', ')) : '—';
  if (typeof v === 'object') return JSON.stringify(v);
  if (typeof v === 'number' && Math.abs(v) >= 1000) return fmtUsd(v);
  return String(v);
}
function frow(label, f, lang) {
  const st = (f && f.status) || 'MISSING';
  const row = H('div', { class: 'sl-row' },
    H('span', { class: 'sl-k' }, label),
    H('span', { class: 'sl-v' }, fval(f)),
    H('span', { class: 'sl-badge', style: `color:${FSTAT[st] || '#6b7690'};border-color:${FSTAT[st] || '#6b7690'}` }, st));
  if (f && f.note) row.append(H('div', { class: 'sl-note' }, f.note));
  if (f && f.provenance) row.append(H('div', { class: 'sl-prov' }, f.provenance));
  return row;
}
export function renderSlice(mount, s, lang) {
  mount.replaceChildren();
  if (!s || !s.entity) { mount.append(H('div', { class: 'surf-empty' }, L(lang, 'СРЕЗ НЕДОСТУПЕН', 'SLICE NOT AVAILABLE'))); return; }
  const wrap = H('div', { class: 'surf' });
  const res = s.result || {};
  wrap.append(H('div', { class: 'sl-hero' },
    H('div', { class: 'sl-title' }, s.entity.label, H('span', { class: 'sl-id' }, s.entity.id)),
    H('div', { class: 'sl-result' }, (res.label && res.label.value) || '—'),
    H('div', { class: 'sl-reason' }, (res.reason && res.reason.value) || '')));
  // chain stepper
  const stepper = H('div', { class: 'sl-chain' });
  (s.chain_stages || []).forEach((st, i) => {
    stepper.append(H('span', { class: 'sl-step' }, st));
    if (i < s.chain_stages.length - 1) stepper.append(H('span', { class: 'sl-arrow' }, '→'));
  });
  wrap.append(stepper);
  const sec = (title, obj, keys) => {
    wrap.append(H('div', { class: 'surf-h' }, title));
    (keys || Object.keys(obj || {})).forEach(k => { if (obj && obj[k]) wrap.append(frow(k, obj[k], lang)); });
  };
  sec(L(lang, 'ВОЗМОЖНОСТЬ', 'OPPORTUNITY'), s.opportunity);
  sec(L(lang, 'СТРАТЕГИЯ', 'STRATEGY'), s.strategy);
  // RISK gates prominently (the WHY)
  wrap.append(H('div', { class: 'surf-h' }, L(lang, 'РИСК — ДЕТЕРМИНИРОВАННЫЕ ГЕЙТЫ', 'RISK — DETERMINISTIC GATES')));
  const risk = s.risk || {};
  wrap.append(H('div', { class: 'sl-pol' }, 'RiskPolicy ' + ((risk.policy_version || {}).value || '') + ' · ' + ((risk.policy_kind || {}).value || '')));
  ((risk.gates || {}).value || []).forEach(g => {
    wrap.append(H('div', { class: 'sl-gate ' + (g.pass ? 'ok' : 'bad') },
      H('span', { class: 'sl-gate-m' }, g.pass ? '✓' : '⛔'),
      H('span', { class: 'sl-gate-r' }, g.rule),
      H('span', { class: 'sl-gate-i' }, String(g.input))));
  });
  sec(L(lang, 'КАПИТАЛ', 'CAPITAL'), s.capital);
  sec(L(lang, 'ПОЗИЦИЯ (ПАСПОРТ)', 'POSITION (PASSPORT)'), s.position);
  // evidence / why edges
  wrap.append(H('div', { class: 'surf-h' }, L(lang, 'ДОКАЗАТЕЛЬСТВА / WHY', 'EVIDENCE / WHY')));
  const edges = ((s.why || {}).missing_edges || {}).value || [];
  if (edges.length) wrap.append(H('div', { class: 'sl-edges' }, L(lang, 'Недостающие связи: ', 'Missing edges: ') + edges.join(' · ')));
  wrap.append(H('div', { class: 'surf-foot' }, H('span', { class: 'surf-prov' }, s.note || '')));
  mount.append(wrap);
}

// ── COMPARISON (factual side-by-side; not a ranking/recommendation) ──────────────────────
const CMP_LABELS = {
  evidence: ['ДОКАЗАНО APY', 'APY EVIDENCE'], apy_pct: ['APY %', 'APY %'],
  position_apy: ['APY НА ПОЗИЦИИ', 'POSITION APY'], tvl_usd: ['TVL', 'TVL'], tvl_source: ['ИСТОЧНИК TVL', 'TVL SOURCE'],
  strategy_binding: ['СВЯЗЬ СО СТРАТЕГИЕЙ', 'STRATEGY BINDING'], candidate_strategies: ['СТРАТЕГИЙ-КАНДИДАТОВ', 'CANDIDATE STRATEGIES'],
  held: ['ДЕРЖИМ', 'HELD'], paper_capital_usd: ['PAPER КАПИТАЛ', 'PAPER CAPITAL'],
  risk_gates_passed: ['ГЕЙТЫ РИСКА', 'RISK GATES'], freshness: ['СВЕЖЕСТЬ', 'FRESHNESS'],
  result: ['ИТОГ', 'RESULT'], missing_or_partial_fields: ['НЕТ ДАННЫХ (ПОЛЕЙ)', 'MISSING FIELDS'],
};
function cmpCell(k, v) {
  if (k === 'held') return v ? '✓' : '—';
  if (k === 'paper_capital_usd' || k === 'tvl_usd') return v ? fmtUsd(v) : '—';
  if (v == null) return '—';
  return String(v);
}
export function renderCompare(mount, c, lang) {
  mount.replaceChildren();
  if (!c || !c.a) { mount.append(H('div', { class: 'surf-empty' }, L(lang, 'СРАВНЕНИЕ НЕДОСТУПНО', 'COMPARISON NOT AVAILABLE'))); return; }
  const wrap = H('div', { class: 'surf' });
  wrap.append(H('div', { class: 'surf-h' }, L(lang, 'СРАВНЕНИЕ ОБЪЕКТОВ — ФАКТЫ, НЕ РЕЙТИНГ', 'OBJECT COMPARISON — FACTS, NOT A RANKING')));
  const tbl = H('div', { class: 'cmp' });
  tbl.append(H('div', { class: 'cmp-row cmp-head' },
    H('span', { class: 'cmp-k' }, ''), H('span', { class: 'cmp-a' }, c.a.protocol), H('span', { class: 'cmp-b' }, c.b.protocol)));
  (c.rows || []).forEach(k => {
    const av = cmpCell(k, c.a[k]), bv = cmpCell(k, c.b[k]);
    const diff = av !== bv;
    tbl.append(H('div', { class: 'cmp-row' + (diff ? ' cmp-diff' : '') },
      H('span', { class: 'cmp-k' }, (CMP_LABELS[k] ? CMP_LABELS[k][lang === 'ru' ? 0 : 1] : k)),
      H('span', { class: 'cmp-a' }, av), H('span', { class: 'cmp-b' }, bv)));
  });
  wrap.append(tbl);
  wrap.append(H('div', { class: 'surf-foot' }, H('span', { class: 'surf-prov' }, c.note || '')));
  mount.append(wrap);
}

// ── VOICE ──────────────────────────────────────────────────────────────────────────────
const VOICE_LOG_KEY = 'sos.voicelog';
const loadLog = () => { try { return JSON.parse(localStorage.getItem(VOICE_LOG_KEY) || '[]'); } catch { return []; } };
const saveLog = (l) => { try { localStorage.setItem(VOICE_LOG_KEY, JSON.stringify(l.slice(-40))); } catch { /* non-canonical UI log */ } };

// Loopback voice endpoint (studio_shell/voice_server.py). When absent (plain http.server) the UI
// degrades to browser STT + local drafts, and says so — never silently pretending a canonical write.
const OWNER_TOKEN = (typeof window !== 'undefined' && window.__OWNER_REMOTE_TOKEN) || '';
const api = async (path, body) => {
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (OWNER_TOKEN) headers['X-Owner-Token'] = OWNER_TOKEN;   // per-run CSRF token (write routes)
    const opt = body === undefined ? {} : { method: 'POST', headers, body: JSON.stringify(body) };
    const r = await fetch(path, opt);
    return await r.json();
  } catch (e) { return { ok: false, error: String(e && e.message || e), _neterr: true }; }
};
let _health = null;
const getHealth = async () => {
  if (_health) return _health;
  try { _health = await (await fetch('/voice/health')).json(); } catch { _health = { stt_engine: 'NONE', capabilities: {} }; }
  return _health;
};

// intent classifier — RED first (safety), then YELLOW (confirm), then GREEN (execute now).
// NOTE: no JS `\b` around Cyrillic — `\b` is ASCII-only (Cyrillic isn't `\w`), so `\bпереведи`
// never matches and a money command would leak into the GREEN fallback. Substring match instead
// (and for RED, over-matching toward BLOCK is the safe direction).
const RED_RE = /(перевед|переведи|перевес|перевод|перечисл|продай|продать|продаж|купи|купить|покуп|выведи|вывести|вывод|сними|снять|подпиш|подпис|включи\s*(live|исполнен|реальн|торг)|перейти\s*на\s*live|запусти\s*исполнен|(измени|поменяй|подними|снизь|поставь)\s*(риск|ставк|порог|лимит|политик|risk|rate|limit|policy)|kill.?switch|стоп-?кран|отключи\s*(стоп|кран|защит)|move\s*(capital|funds|money)|transfer|sell|buy\b|withdraw|deposit|\bsign\b|enable\s*(live|execution|real|trading)|go\s*live|change\s*(the\s*)?(rate|risk|policy|limit)|disable\s*(stop|kill)|custody|private\s*key)/i;
const YELLOW_TASK_RE = /(созда(й|ть)\s*задач|нов(ая|ую)\s*задач|поставь\s*задач|задача\b|задачу\b|напомни|поручи|create\s*(a\s*)?task|new\s*task|\btodo\b|remind|dispatch|отправь\s*на\s*выполнен)/i;
const YELLOW_DEC_RE = /(запиши\s*решени|зафиксируй\s*решени|прими\s*решени|record\s*(a\s*)?decision|log\s*decision|decision:)/i;
const GREEN_IDEA_RE = /(иде(я|ю|и)|запиши\s*иде|заметк|запиши\s*заметк|note|\bidea\b|черновик|capture)/i;
const GREEN_WHY_RE = /(почему|\bwhy\b)/i;
const NAV_MAP = [
  [/(обзор|главн|overview|home|dashboard)/i, 'home'],
  [/(капитал|портфел|деньг|баланс|позици|capital|holdings|portfolio|\bmoney\b|balance)/i, 'capital'],
  [/(стратег|strateg)/i, 'strategies'],
  [/(систем|флот|агент|system|fleet|agents|health)/i, 'system'],
  [/(вселенн|граф|карт|universe|graph|\bmap\b)/i, 'universe'],
  [/(решени|decision)/i, 'decisions'],
  [/(почему|\bwhy\b|трасс|trace)/i, 'why'],
];

export function classifyIntent(text) {
  const t = (text || '').trim();
  if (!t) return { zone: 'NONE', intent: 'empty', normalized: '' };
  if (RED_RE.test(t)) return { zone: 'RED', intent: 'financial/execution', normalized: t };
  if (YELLOW_TASK_RE.test(t)) return { zone: 'YELLOW', intent: 'create_task', normalized: t };
  if (YELLOW_DEC_RE.test(t)) return { zone: 'YELLOW', intent: 'record_decision', normalized: t };
  // navigation / query / why are GREEN
  const nav = NAV_MAP.find(([re]) => re.test(t));
  if (GREEN_WHY_RE.test(t)) return { zone: 'GREEN', intent: 'why', normalized: t, view: 'why' };
  if (nav) {
    const q = /(сколько|какой|каков|что|какая|какие|status|how\s*much|what|show|state)/i.test(t);
    return { zone: 'GREEN', intent: q ? 'query' : 'navigate', normalized: t, view: nav[1] };
  }
  if (GREEN_IDEA_RE.test(t)) return { zone: 'GREEN', intent: 'capture_idea', normalized: t };
  return { zone: 'GREEN', intent: 'query', normalized: t, view: null };
}

export function renderVoice(mount, ctx) {
  const { lang, nav } = ctx;
  mount.replaceChildren();
  const wrap = H('div', { class: 'surf voice' });

  wrap.append(H('div', { class: 'surf-h' }, L(lang, 'ГОЛОС — ПУЛЬТ ВЛАДЕЛЬЦА', 'VOICE — OWNER REMOTE')));

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const note = H('div', { class: 'voice-note' }, L(lang, 'Проверяю локальный STT…', 'Checking local STT…'));
  wrap.append(note);

  // mic + text input
  const status = H('div', { class: 'voice-status' }, '');
  const mic = H('button', { class: 'voice-mic', 'aria-label': 'voice' }, H('span', { class: 'voice-mic-ico' }, '◉'));
  const input = H('input', { class: 'voice-text', type: 'text', placeholder: L(lang, 'Скажи или напиши команду…', 'Speak or type a command…') });
  const submit = H('button', { class: 'voice-go' }, L(lang, 'РАЗОБРАТЬ', 'PARSE'));
  const result = H('div', { class: 'voice-result' });
  const logHost = H('div', { class: 'voice-log' });

  const renderLog = () => {
    const log = loadLog();
    logHost.replaceChildren(H('div', { class: 'surf-h sm' }, L(lang, 'ЛОКАЛЬНЫЙ ЖУРНАЛ ГОЛОСА', 'LOCAL VOICE LOG'),
      H('span', { class: 'surf-count' }, String(log.length))));
    if (!log.length) { logHost.append(H('div', { class: 'voice-logempty' }, L(lang, 'пусто · не канонический источник', 'empty · not a canonical source'))); return; }
    log.slice().reverse().forEach(e => {
      logHost.append(H('div', { class: 'voice-logrow z-' + e.zone },
        H('div', { class: 'vlr-top' }, H('span', { class: 'vlr-zone' }, e.zone), H('span', { class: 'vlr-intent' }, e.intent),
          H('span', { class: 'vlr-conf' }, e.confirmation), H('span', { class: 'vlr-ts' }, e.ts)),
        H('div', { class: 'vlr-tx' }, '“' + e.transcript + '”'),
        H('div', { class: 'vlr-out' }, e.outcome)));
    });
  };

  const record = (entry) => { const log = loadLog(); log.push(entry); saveLog(log); renderLog(); };
  const now = () => new Date().toISOString().replace('T', ' ').slice(0, 19);

  const ok = (msg) => result.append(H('div', { class: 'voice-ok' }, msg));
  const warn = (msg) => result.append(H('div', { class: 'voice-empty' }, msg));

  const handle = async (text) => {
    const c = classifyIntent(text);
    result.replaceChildren();
    const base = { transcript: text, normalized: c.normalized, ts: now(), intent: c.intent, zone: c.zone };
    const h = await getHealth();
    const cap = h.capabilities || {};

    if (c.zone === 'NONE') { warn(L(lang, 'Пустая команда.', 'Empty command.')); return; }

    // interpreted command card
    result.append(H('div', { class: 'voice-card z-' + c.zone },
      H('div', { class: 'vc-zone z-' + c.zone }, c.zone + ' · ' + c.intent),
      H('div', { class: 'vc-tx' }, '“' + text + '”')));

    if (c.zone === 'RED') {
      // never any write; the server ALSO refuses RED text — the block is client + server
      result.append(H('div', { class: 'voice-red' },
        L(lang, '⛔ Голос НИКОГДА не исполняет движение капитала, подпись, изменение риска/ставок/лимитов или включение live. Максимум — предложение-заметка для владельца.',
                '⛔ Voice NEVER executes moving capital, signing, changing risk/rates/limits, or enabling live. At most it drafts a proposal note for the Owner.')));
      const propose = H('button', { class: 'voice-go' }, L(lang, 'Создать предложение-заметку', 'Create proposal note'));
      propose.addEventListener('click', async () => {
        propose.disabled = true;
        const r = cap.canonical_idea ? await api('/voice/idea', { transcript: 'ПРЕДЛОЖЕНИЕ (не исполнять): ' + text, confirmed: true }) : { _neterr: true };
        if (r.ok) { record({ ...base, zone: 'RED', intent: 'proposal', confirmation: 'DRAFT_NOTE', entity_id: r.id, outcome: L(lang, 'Предложение записано заметкой (не исполнение): ', 'Proposal saved as a note (not execution): ') + r.id }); ok(L(lang, '✓ Предложение-заметка: ', '✓ Proposal note: ') + r.id); }
        else { record({ ...base, zone: 'RED', intent: 'proposal', confirmation: 'DRAFT_LOCAL', entity_id: null, outcome: L(lang, 'Локальный черновик (сервер недоступен).', 'Local draft (server unavailable).') }); warn(L(lang, 'Записано локальным черновиком (loopback-сервер не запущен).', 'Recorded as a local draft (loopback server not running).')); }
      });
      result.append(propose);
      record({ ...base, confirmation: 'BLOCKED', entity_id: null, outcome: L(lang, 'Заблокировано правилом безопасности (RED). Ничего не исполнено.', 'Blocked by safety rule (RED). Nothing executed.') });
      return;
    }

    if (c.zone === 'YELLOW') {
      const isDecision = c.intent === 'record_decision';
      const kind = isDecision ? L(lang, 'РЕШЕНИЕ', 'DECISION') : L(lang, 'ЗАДАЧА', 'TASK');
      result.append(H('div', { class: 'voice-draft' },
        H('div', { class: 'vd-h' }, L(lang, 'ЧЕРНОВИК ', 'DRAFT ') + kind + L(lang, ' — подтверди', ' — confirm')),
        H('div', { class: 'vd-body' }, text)));
      const confirm = H('button', { class: 'voice-go' }, L(lang, 'Подтвердить', 'Confirm'));
      const cancel = H('button', { class: 'voice-cancel' }, L(lang, 'Отмена', 'Cancel'));
      confirm.addEventListener('click', async () => {
        confirm.disabled = cancel.disabled = true;
        if (isDecision) {
          // no accepted canonical decision write — surface honestly, keep DRAFT
          await api('/voice/decision', { transcript: text, confirmed: true });
          record({ ...base, confirmation: 'CONFIRMED', entity_id: null, outcome: 'CANONICAL_DECISION_WRITE=NOT_AVAILABLE — ' + L(lang, 'сохранено черновиком.', 'kept as draft.') });
          result.append(H('div', { class: 'voice-red' }, L(lang,
            'CANONICAL_DECISION_WRITE = НЕДОСТУПНО. Принятого интерфейса записи решения нет — оставлено ЧЕРНОВИКОМ. Можно сохранить как идею для последующего ADR.',
            'CANONICAL_DECISION_WRITE = NOT_AVAILABLE. No accepted decision-write interface — kept as a DRAFT. You may save it as an idea to later formalize into an ADR.')));
          if (cap.canonical_idea) {
            const asIdea = H('button', { class: 'voice-go' }, L(lang, 'Сохранить как идею', 'Save as idea'));
            asIdea.addEventListener('click', async () => { asIdea.disabled = true; const r = await api('/voice/idea', { transcript: 'РЕШЕНИЕ-ЧЕРНОВИК: ' + text, confirmed: true }); if (r.ok) { record({ ...base, intent: 'decision_as_idea', confirmation: 'SAVED', entity_id: r.id, outcome: r.id }); ok(L(lang, '✓ Сохранено идеей: ', '✓ Saved as idea: ') + r.id); } });
            result.append(asIdea);
          }
          return;
        }
        // canonical TASK creation via existing owner intake
        const r = cap.canonical_task ? await api('/voice/task', { transcript: text, normalized: c.normalized, confirmed: true }) : { _neterr: true };
        if (r.ok && r.id) {
          record({ ...base, confirmation: 'CONFIRMED', entity_id: r.id, outcome: L(lang, 'Каноническая задача создана: ', 'Canonical task created: ') + r.id });
          ok(L(lang, '✓ Каноническая задача создана (', '✓ Canonical task created (') + r.canonical + '):\n' + r.id);
        } else {
          record({ ...base, confirmation: 'CONFIRMED_NO_WRITE', entity_id: null, outcome: (r.error || 'server unavailable') });
          warn(L(lang, 'Подтверждено, но каноническая запись НЕ выполнена: ', 'Confirmed, but canonical write did NOT happen: ')
            + (r._neterr ? L(lang, 'loopback-сервер не запущен (запусти voice_server.py).', 'loopback server not running (start voice_server.py).') : (r.error || '')));
        }
      });
      cancel.addEventListener('click', () => {
        confirm.disabled = cancel.disabled = true;
        record({ ...base, confirmation: 'CANCELLED', entity_id: null, outcome: L(lang, 'Отменено владельцем.', 'Cancelled by owner.') });
        warn(L(lang, 'Отменено.', 'Cancelled.'));
      });
      result.append(H('div', { class: 'voice-acts' }, confirm, cancel));
      return;
    }

    // GREEN — execute immediately (read-only / navigation / draft capture)
    if (c.intent === 'capture_idea') {
      // idea → the accepted owner home docs/ideas (non-executing; agents don't act until #promote)
      const r = cap.canonical_idea ? await api('/voice/idea', { transcript: text, confirmed: true }) : { _neterr: true };
      if (r.ok && r.id) { record({ ...base, confirmation: 'AUTO', entity_id: r.id, outcome: L(lang, 'Идея записана: ', 'Idea captured: ') + r.id }); ok(L(lang, '✓ Идея записана (docs/ideas): ', '✓ Idea captured (docs/ideas): ') + r.id); }
      else { const id = 'idea-' + Date.now().toString(36); record({ ...base, confirmation: 'AUTO', entity_id: id, outcome: L(lang, 'Локальный черновик (сервер недоступен).', 'Local draft (server unavailable).') }); ok(L(lang, '✓ Идея записана локальным черновиком (' + id + ').', '✓ Idea captured as local draft (' + id + ').')); }
      return;
    }
    if (c.intent === 'why') {
      record({ ...base, confirmation: 'AUTO', entity_id: 'why', outcome: L(lang, 'Открыта трасса решения.', 'Opened decision trace.') });
      nav.go('why'); result.append(H('div', { class: 'voice-ok' }, L(lang, '✓ Открываю трассу «Почему?».', '✓ Opening WHY trace.')));
      return;
    }
    if (c.intent === 'navigate' && c.view) {
      record({ ...base, confirmation: 'AUTO', entity_id: c.view, outcome: L(lang, 'Переход к ' + c.view, 'Navigated to ' + c.view) });
      nav.go(c.view); result.append(H('div', { class: 'voice-ok' }, L(lang, '✓ Открываю: ', '✓ Opening: ') + c.view));
      return;
    }
    // query — answer read-only from ctx data
    const ans = nav.answer(c.view, text);
    record({ ...base, confirmation: 'AUTO', entity_id: c.view, outcome: (L(lang, 'Ответ: ', 'Answer: ') + ans).slice(0, 160) });
    result.append(H('div', { class: 'voice-answer' }, ans));
    if (c.view) result.append(H('button', { class: 'voice-go', onclick: () => nav.go(c.view) }, L(lang, 'Открыть', 'Open') + ' → ' + c.view));
  };

  submit.addEventListener('click', () => { handle(input.value); });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') handle(input.value); });

  // Mic strategy decided by /voice/health: LOCAL_WHISPER (record → loopback endpoint) preferred;
  // browser SpeechRecognition is the fallback. Both are local; no paid API either way.
  const wireBrowserSR = () => {
    if (!SR) { mic.disabled = true; mic.classList.add('disabled'); return; }
    let rec = null, listening = false;
    mic.addEventListener('click', () => {
      if (listening && rec) { rec.stop(); return; }
      rec = new SR(); rec.lang = lang === 'ru' ? 'ru-RU' : 'en-US'; rec.interimResults = false; rec.maxAlternatives = 1;
      rec.onstart = () => { listening = true; mic.classList.add('live'); status.textContent = L(lang, 'Слушаю (браузер)…', 'Listening (browser)…'); };
      rec.onerror = (e) => { status.textContent = L(lang, 'Ошибка распознавания: ', 'Recognition error: ') + (e.error || ''); mic.classList.remove('live'); listening = false; };
      rec.onend = () => { mic.classList.remove('live'); listening = false; if (/…$/.test(status.textContent)) status.textContent = ''; };
      rec.onresult = (e) => { const t = e.results[0][0].transcript; input.value = t; status.textContent = ''; handle(t); };
      try { rec.start(); } catch { status.textContent = L(lang, 'Не удалось начать запись.', 'Could not start recording.'); }
    });
  };
  const wireLocalWhisper = () => {
    let mr = null, chunks = [], recording = false;
    mic.addEventListener('click', async () => {
      if (recording && mr) { mr.stop(); return; }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { wireBrowserSR(); status.textContent = L(lang, 'Микрофон недоступен — браузерный ввод.', 'Mic unavailable — browser input.'); return; }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mr = new MediaRecorder(stream); chunks = [];
        mr.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
        mr.onstart = () => { recording = true; mic.classList.add('live'); status.textContent = L(lang, 'Запись… (локальный whisper)', 'Recording… (local whisper)'); };
        mr.onstop = async () => {
          recording = false; mic.classList.remove('live'); status.textContent = L(lang, 'Распознаю локально…', 'Transcribing locally…');
          stream.getTracks().forEach(t => t.stop());
          const blob = new Blob(chunks, { type: chunks[0] && chunks[0].type || 'audio/webm' });
          try {
            const r = await fetch('/voice/transcribe?lang=' + lang, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: blob });
            const j = await r.json();
            if (j.text) { input.value = j.text; status.textContent = 'LOCAL_WHISPER · ' + (j.via || ''); handle(j.text); }
            else { status.textContent = L(lang, 'STT: ', 'STT: ') + (j.error || 'no text'); }
          } catch (e) { status.textContent = L(lang, 'STT-запрос не удался: ', 'STT request failed: ') + (e.message || e); }
        };
        mr.start();
      } catch (e) { status.textContent = L(lang, 'Нет доступа к микрофону: ', 'Mic permission denied: ') + (e.message || e); }
    });
  };

  wrap.append(H('div', { class: 'voice-inputbar' }, mic, H('div', { class: 'voice-trow' }, input, submit)), status, result);

  // resolve health → set the note honestly + wire the right mic path
  getHealth().then(h => {
    const eng = h.stt_engine || 'NONE';
    const canT = h.capabilities && h.capabilities.canonical_task;
    if (eng === 'LOCAL_WHISPER' && h.capabilities && h.capabilities.transcribe) {
      note.textContent = L(lang,
        'STT: ЛОКАЛЬНЫЙ WHISPER на этой машине (loopback, без внешних API). Каноническая задача: ' + (canT ? 'ДА' : 'нет') + '. Решение: НЕДОСТУПНО.',
        'STT: LOCAL WHISPER on this machine (loopback, no external API). Canonical task: ' + (canT ? 'YES' : 'no') + '. Decision: NOT_AVAILABLE.');
      wireLocalWhisper();
    } else {
      note.textContent = SR
        ? L(lang, 'Loopback-сервер не запущен: браузерный STT + локальные черновики. Продакшн STT — локальный whisper (voice_server.py).',
              'Loopback server not running: browser STT + local drafts. Production STT is local whisper (voice_server.py).')
        : L(lang, 'Loopback-сервер не запущен и браузерный STT недоступен — используй текст.',
              'Loopback server not running and browser STT unavailable — use text.');
      wireBrowserSR();
    }
  });

  // safety legend
  wrap.append(H('div', { class: 'voice-legend' },
    H('span', { class: 'vl z-GREEN' }, L(lang, 'ЗЕЛЁНЫЙ: навигация · запрос · черновик — сразу', 'GREEN: navigate · query · draft — immediate')),
    H('span', { class: 'vl z-YELLOW' }, L(lang, 'ЖЁЛТЫЙ: задача · решение — с подтверждением', 'YELLOW: task · decision — needs confirm')),
    H('span', { class: 'vl z-RED' }, L(lang, 'КРАСНЫЙ: деньги · подпись · риск · live — НИКОГДА', 'RED: money · signing · risk · live — NEVER'))));

  wrap.append(logHost); renderLog();
  mount.append(wrap);
}
