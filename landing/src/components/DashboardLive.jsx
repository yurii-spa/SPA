import { useState, useEffect, useCallback, useRef } from 'react';

/*
 * DashboardLive — the COMMAND CENTER for earn-defi.com.
 *
 * This is the single canonical /dashboard. It is a navigable hub with six sections,
 * each surfacing a different surface of the system with LIVE data + honest framing:
 *
 *   1. Overview            — track-days ring, paper portfolio, go-live X/29, fleet + safety.
 *   2. Parallel Strategies — the strategy-lab sleeves running in parallel (no capital).
 *   3. Tournament          — the live leaderboard (ranked by net-return; Sharpe honestly n/a).
 *   4. Research Desks       — Rates Desk (GO), BTC/ETH angle, RWA backstop + refusal verdicts.
 *   5. System              — agent fleet, the safety ladder, deep links.
 *   6. How to use          — friendly legend: paper vs advisory vs go-live, the honest caveats.
 *
 * It renders inside the site <Layout> (Console design tokens via CSS vars) so it matches
 * earn-defi.com pixel-for-pixel. Bilingual (EN|RU) via the site's spa_lang mechanism.
 *
 * HONESTY CONTRACT:
 *   - /api/ssot/facts is the SINGLE SOURCE OF TRUTH for the headline (decides live/offline).
 *   - Every section polls its OWN endpoint(s) independently. A dead endpoint shows "—" /
 *     "offline" for THAT section only and never breaks the others; we never paint stale or
 *     fabricated numbers as live.
 *   - Sleeves are advisory (no capital). The tournament leaderboard is backtest-derived and
 *     flagged not-trustworthy until real history. Refusal-first desks are research. All said
 *     plainly in the UI.
 */

const API =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8765'
    : 'https://api.earn-defi.com';

const POLL_MS = 15_000;
const FETCH_TIMEOUT_MS = 8_000;
const DAYS_NEEDED = 30;
const GATES_TOTAL_FALLBACK = 29;
const GOLIVE_TARGET_FALLBACK = '2026-07-21'; // plan date, labeled as such
const RWA_FLOOR_FALLBACK = 3.4; // structural benchmark, labeled
const NA = '—';

/* ─────────────────────────────────────────────────────────── i18n ───────────────── */
const T = {
  paperBanner: { en: 'PAPER TRADING', ru: 'БУМАЖНАЯ ТОРГОВЛЯ' },
  paperSub: {
    en: 'Virtual $100,000 USDC — no real capital at risk',
    ru: 'Виртуальные $100,000 USDC — реальный капитал не задействован',
  },
  live: { en: 'Live', ru: 'Вживую' },
  offline: { en: 'Offline', ru: 'Офлайн' },
  snapshot: { en: 'Live API offline', ru: 'Живой API недоступен' },
  connecting: { en: 'Connecting…', ru: 'Подключение…' },
  updated: { en: 'Updated', ru: 'Обновлено' },
  refresh: { en: 'Refresh', ru: 'Обновить' },

  /* tabs */
  tabOverview: { en: 'Overview', ru: 'Обзор' },
  tabStrategies: { en: 'Parallel strategies', ru: 'Параллельные стратегии' },
  tabTournament: { en: 'Tournament', ru: 'Турнир' },
  tabDesks: { en: 'Research desks', ru: 'Исследования' },
  tabSystem: { en: 'System', ru: 'Система' },
  tabHelp: { en: 'How to use', ru: 'Как пользоваться' },

  /* overview */
  heroEyebrow: { en: 'The road to go-live', ru: 'Путь к go-live' },
  heroTitle: { en: 'Evidenced track days', ru: 'Подтверждённые дни трека' },
  heroSub: {
    en: 'Only days backed by a real daily-cycle log count. Target: 30 honest days, then owner review.',
    ru: 'Считаются только дни с реальным логом ежедневного цикла. Цель: 30 честных дней, затем ревью владельца.',
  },
  anchor: { en: 'Evidence anchor', ru: 'Якорь подтверждения' },
  target: { en: 'Go-live target', ru: 'Цель go-live' },
  daysLeft: { en: 'days remaining', ru: 'дней осталось' },
  golive: { en: 'Go-live criteria', ru: 'Критерии go-live' },
  goliveSub: {
    en: 'Deterministic checks (ADR-002). All must pass for 7+ consecutive days.',
    ru: 'Детерминированные проверки (ADR-002). Все должны пройти 7+ дней подряд.',
  },
  portfolio: { en: 'Paper portfolio', ru: 'Бумажный портфель' },
  equity: { en: 'Equity', ru: 'Капитал' },
  apyToday: { en: 'APY today', ru: 'APY сегодня' },
  dailyYield: { en: 'Daily yield', ru: 'Доход за день' },
  regime: { en: 'Market regime', ru: 'Рыночный режим' },
  totalReturn: { en: 'Total return', ru: 'Совокупная доходность' },
  nav: { en: 'NAV (reconciled)', ru: 'NAV (сверено)' },
  fleet: { en: 'Agent fleet', ru: 'Парк агентов' },
  fleetSub: {
    en: 'Autonomous launchd agents — daily cycle, monitors, autopush.',
    ru: 'Автономные launchd-агенты — дневной цикл, мониторы, автопуш.',
  },
  healthy: { en: 'Healthy', ru: 'Здоровы' },
  warning: { en: 'Warning', ru: 'Внимание' },
  critical: { en: 'Critical', ru: 'Критич.' },
  safety: { en: 'Safety state', ru: 'Состояние защиты' },
  ofNeeded: { en: 'of 30 needed', ru: 'из 30 нужных' },

  /* parallel strategies */
  sleevesEyebrow: { en: 'Running in parallel · no capital', ru: 'Работают параллельно · без капитала' },
  sleevesTitle: { en: 'Parallel strategies (Strategy Lab)', ru: 'Параллельные стратегии (Strategy Lab)' },
  sleevesIntro: {
    en: 'Several yield strategies (“sleeves”) run side-by-side through one shared backtest + live paper harness — with NO capital — so they can be compared honestly, risk-adjusted, against a real ~RWA T-bill floor. Each is advisory (it opens no live positions). Risk-adjusted metrics stay honestly UNKNOWN until a track is ~30 days deep.',
    ru: 'Несколько yield-стратегий («sleeve’ов») работают рядом через один общий backtest + live-paper харнесс — БЕЗ капитала — чтобы честно сравнить их с поправкой на риск против реального ~RWA-пола T-bills. Каждая — advisory (не открывает live-позиций). Risk-adjusted метрики честно UNKNOWN, пока трек не накопит ~30 дней.',
  },
  sleeveName: { en: 'Sleeve', ru: 'Sleeve' },
  sleeveApy: { en: 'Net APY', ru: 'Net APY' },
  sleeveSharpe: { en: 'Sharpe', ru: 'Sharpe' },
  sleeveDd: { en: 'Max DD', ru: 'Макс. DD' },
  sleeveExcess: { en: 'vs RWA floor', ru: 'к RWA-полу' },
  sleeveStage: { en: 'Promotion', ru: 'Промоушен' },
  sleevesOffline: {
    en: 'Sleeve comparison unavailable — /api/strategy-lab offline.',
    ru: 'Сравнение sleeve’ов недоступно — /api/strategy-lab офлайн.',
  },
  floorNote: { en: 'Benchmarked vs the live tokenized-T-bill (RWA) floor', ru: 'Бенчмарк — живой пол tokenized-T-bills (RWA)' },

  /* tournament */
  tourEyebrow: { en: 'Backtest → paper → live', ru: 'Backtest → paper → live' },
  tourTitle: { en: 'Strategy tournament', ru: 'Турнир стратегий' },
  tourIntro: {
    en: 'Dozens of strategies are ranked by a deterministic backtest. The leaderboard is ranked by NET RETURN — Sharpe is shown as n/a where it degenerates under near-zero stablecoin volatility. This is a backtest ranking, not a live track; the top survivors graduate to shadow paper.',
    ru: 'Десятки стратегий ранжируются детерминированным backtest’ом. Лидерборд ранжирован по NET RETURN — Sharpe показан как n/a там, где он вырождается при почти нулевой волатильности стейблов. Это backtest-ранжирование, не live-трек; лучшие выходят в shadow paper.',
  },
  tourRank: { en: 'Rank', ru: 'Ранг' },
  tourStrategy: { en: 'Strategy', ru: 'Стратегия' },
  tourReturn: { en: 'Net return', ru: 'Net доходность' },
  tourPhase: { en: 'Phase', ru: 'Фаза' },
  tourTested: { en: 'Strategies tested', ru: 'Протестировано стратегий' },
  tourPaper: { en: 'In shadow paper', ru: 'В shadow paper' },
  tourNotTrust: {
    en: 'Backtest ranking on synthetic/mock history — NOT a trustworthy live ranking yet.',
    ru: 'Backtest-ранжирование на синтетической истории — пока НЕ доверенный live-ранкинг.',
  },
  tourTrust: { en: 'Backtest ranking · deterministic', ru: 'Backtest-ранжирование · детерминир.' },
  tourOffline: {
    en: 'Leaderboard unavailable — /api/tournament offline.',
    ru: 'Лидерборд недоступен — /api/tournament офлайн.',
  },
  fullTournament: { en: 'Full tournament →', ru: 'Полный турнир →' },

  /* desks */
  desksEyebrow: { en: 'Structural desk · advisory research', ru: 'Структурный desk · advisory-исследование' },
  desksTitle: { en: 'Research desks — BTC / ETH / RWA', ru: 'Исследования — BTC / ETH / RWA' },
  desksIntro: {
    en: 'The structural desk’s thesis: the edge is not yield, it is honest measurement & underwriting of risk others ignore. Three research arcs, all advisory (no capital): a validated Rates Desk, the BTC/ETH angle, and an RWA collateral safety board. Live data below, plain-language explainers, deep links to the full pages.',
    ru: 'Тезис структурного desk’а: edge — не доходность, а честное измерение и андеррайтинг риска, который остальные игнорируют. Три research-арки, все advisory (без капитала): валидированный Rates Desk, BTC/ETH-угол и RWA safety board. Ниже — живые данные, объяснения простым языком и ссылки на полные страницы.',
  },
  ratesTitle: { en: 'Rates Desk', ru: 'Rates Desk' },
  ratesVerdict: { en: 'GO · validated', ru: 'GO · валидирован' },
  ratesWhat: {
    en: 'A refusal-first pricing engine: it harvests genuine mispriced carry and REFUSES yield that is just tail-risk compensation. FixedCarry is validated and runs live in paper.',
    ru: 'Refusal-first ценовой движок: харвестит реальный mispriced carry и ОТКАЗЫВАЕТСЯ от доходности, которая лишь компенсация хвостового риска. FixedCarry валидирован и работает live в paper.',
  },
  ratesSurface: { en: 'Rate surface quotes', ru: 'Котировки ставок' },
  ratesOpps: { en: 'Opportunities', ru: 'Возможности' },
  ratesEntries: { en: 'Entries', ru: 'Входы' },
  ratesRefusals: { en: 'Refusals', ru: 'Отказы' },
  ratesTrackDays: { en: 'Carry track', ru: 'Carry-трек' },
  refusalTitle: { en: 'Refusal verdicts (per underlying)', ru: 'Вердикты отказа (по активам)' },
  refusalWhat: {
    en: 'Daily tail-risk verdict per underlying: SAFE / WATCH / REFUSE. This is the credibility artifact — we publish what we refuse, not only what we trade.',
    ru: 'Ежедневный вердикт хвостового риска по каждому активу: SAFE / WATCH / REFUSE. Это артефакт доверия — мы публикуем то, от чего отказываемся, а не только то, чем торгуем.',
  },
  btcEthTitle: { en: 'BTC / ETH angle', ru: 'BTC / ETH угол' },
  btcEthWhat: {
    en: 'BTC lending is read-only advisory at ~0% (BTC is barely borrowed on-chain — honest, not hidden). The recommended ETH approach is eth_lst_neutral: a plain LST (stETH/rETH) hedged with a short perp, β≈0.',
    ru: 'BTC-кредитование — read-only advisory с ~0% (BTC почти не занимают on-chain — честно, не спрятано). Рекомендуемый ETH-подход — eth_lst_neutral: обычный LST (stETH/rETH), захеджированный коротким перпом, β≈0.',
  },
  rwaTitle: { en: 'RWA collateral safety board', ru: 'RWA safety board' },
  rwaVerdict: { en: 'measurement-GO', ru: 'measurement-GO' },
  rwaWhat: {
    en: 'Measures the gap between tokenized-RWA marketing NAV and real liquidation NAV. Measurement is GO; the underwriting book is gated on relationships/capital/legal off-code.',
    ru: 'Измеряет разрыв между маркетинговой NAV токенизированных RWA и реальной liquidation-NAV. Измерение — GO; сам андеррайтинг гейтится на отношениях/капитале/legal вне кода.',
  },
  deskOffline: { en: 'desk offline', ru: 'desk офлайн' },
  deepRates: { en: 'Open Rates Desk →', ru: 'Открыть Rates Desk →' },
  deepStructural: { en: 'Structural desk →', ru: 'Структурный desk →' },
  deepRwa: { en: 'RWA backstop →', ru: 'RWA backstop →' },
  deepResearch: { en: 'Research journal →', ru: 'Журнал исследований →' },

  /* exit-NAV waterfall (Panel A) */
  exitTitle: { en: 'Exit NAV by size', ru: 'Exit NAV по размеру' },
  exitSub: {
    en: 'Modeled net proceeds if you exited at each size, from real on-chain Pendle depth. Conservative lower bound — not realized exits.',
    ru: 'Моделируемые чистые поступления при выходе на каждом размере, из реальной on-chain Pendle-глубины. Консервативная нижняя граница — не реализованные выходы.',
  },
  exitModelChip: { en: 'advisory · conservative model', ru: 'advisory · консервативная модель' },
  exitIllustrative: { en: 'illustrative · hypothetical book', ru: 'иллюстративно · гипотетич. книга' },
  exitIllustrativeNote: {
    en: 'Illustrative schedule on a real market’s contemporaneous on-chain depth — it demonstrates the model. This is NOT our live book.',
    ru: 'Иллюстративный график на реальной on-chain глубине рынка — демонстрирует модель. Это НЕ наша live-книга.',
  },
  exitLiveBook: { en: 'Our live book', ru: 'Наша live-книга' },
  exitLiveThin: {
    en: 'Our actual book is {x} — too small to model an exit at these sizes; we show holes, not fabricated fills.',
    ru: 'Наша реальная книга — {x} — слишком мала, чтобы моделировать выход на этих размерах; мы показываем дыры, а не выдуманные заливки.',
  },
  exitNet: { en: 'net', ru: 'чистыми' },
  exitHaircut: { en: 'haircut', ru: 'хейркат' },
  exitTime: { en: 'time-to-exit', ru: 'время выхода' },
  exitDepthLimited: { en: 'depth-limited', ru: 'ограничено глубиной' },
  exitMethodology: { en: 'Methodology →', ru: 'Методология →' },
  exitOffline: { en: 'Exit-NAV unavailable — /api/rates-desk/exit-nav offline.', ru: 'Exit-NAV недоступен — /api/rates-desk/exit-nav офлайн.' },

  /* public refusal log (Panel B) */
  refLogTitle: { en: 'Public refusal log', ru: 'Публичный журнал отказов' },
  refLogSub: {
    en: 'Every declined trade, with a plain-language reason and a tamper-evident proof. We publish what we refuse, not only what we trade.',
    ru: 'Каждая отклонённая сделка — с объяснением простым языком и защищённым от подмены доказательством. Мы публикуем отказы, а не только сделки.',
  },
  refChainOk: { en: 'chain verified', ru: 'цепочка проверена' },
  refChainBroken: { en: 'INTEGRITY BROKEN', ru: 'ЦЕЛОСТНОСТЬ НАРУШЕНА' },
  refChainUnknown: { en: 'verifying…', ru: 'проверка…' },
  refChainUnavailable: { en: 'verification unavailable', ru: 'проверка недоступна' },
  refEntries: { en: 'entries', ru: 'входов' },
  refRefusals: { en: 'refusals', ru: 'отказов' },
  refHeadAnchorNote: {
    en: 'Head is a re-based sliding-window mirror (last 2000 decisions): stable across appends, re-bases when old rows are evicted. The immutable all-time ledger is audit_chain.jsonl.',
    ru: 'Голова — это пересчитываемое зеркало скользящего окна (последние 2000 решений): стабильна при дозаписи, пересчитывается при вытеснении старых строк. Неизменяемый журнал за всё время — audit_chain.jsonl.',
  },
  refProof: { en: 'proof', ru: 'доказательство' },
  refProofSpec: { en: 'chain spec →', ru: 'спецификация цепочки →' },
  refLogOffline: { en: 'Refusal log unavailable — /api/rates-desk/refusals offline.', ru: 'Журнал отказов недоступен — /api/rates-desk/refusals офлайн.' },

  /* system */
  sysEyebrow: { en: 'Operations', ru: 'Эксплуатация' },
  sysTitle: { en: 'System & safety', ru: 'Система и защита' },
  sysIntro: {
    en: 'The autonomous fleet that keeps the daily cycle, monitors and autopush running — and the deterministic safety ladder that governs the book (RiskPolicy v1.0, LLM-free).',
    ru: 'Автономный парк, который держит дневной цикл, мониторы и автопуш — и детерминированная лестница защиты, управляющая портфелем (RiskPolicy v1.0, без LLM).',
  },
  ladderTitle: { en: 'Safety ladder', ru: 'Лестница защиты' },
  ladderDl: { en: 'Drift watch (DL-01) · 2% drawdown', ru: 'Наблюдение за дрейфом (DL-01) · 2% просадки' },
  ladderSoft: { en: 'Soft de-risk · 5% drawdown — halt new allocations', ru: 'Soft de-risk · 5% просадки — стоп новых аллокаций' },
  ladderHard: { en: 'Hard kill · 10% drawdown — all to cash', ru: 'Hard kill · 10% просадки — всё в кэш' },
  ladderState: { en: 'Current safety state', ru: 'Текущее состояние защиты' },
  deepSystem: { en: 'System hub →', ru: 'Хаб системы →' },
  deepStatus: { en: 'System status →', ru: 'Статус системы →' },
  problemAgents: { en: 'Agents needing attention', ru: 'Агенты, требующие внимания' },
  allHealthy: { en: 'All agents healthy.', ru: 'Все агенты здоровы.' },

  /* help */
  helpEyebrow: { en: 'Legend', ru: 'Легенда' },
  helpTitle: { en: 'How to use this dashboard', ru: 'Как пользоваться этим дашбордом' },
  helpIntro: {
    en: 'This is a live lab notebook, not a fund. Here is how to read each section and what the honest caveats are.',
    ru: 'Это живой лабораторный журнал, не фонд. Вот как читать каждую секцию и какие честные оговорки.',
  },
  clear: { en: 'CLEAR', ru: 'ЧИСТО' },
  armed: { en: 'ARMED', ru: 'ВЗВЕДЕН' },
  pass: { en: 'PASS', ru: 'ПРОЙДЕНО' },
  pending: { en: 'PENDING', ru: 'ОЖИДАНИЕ' },
  fail: { en: 'FAIL', ru: 'ПРОВАЛ' },
  unknown: { en: 'UNKNOWN', ru: 'НЕИЗВ.' },
};

function useLang() {
  const [lang, setLang] = useState('en');
  useEffect(() => {
    function read() {
      try {
        const v = window.localStorage.getItem('spa_lang');
        setLang(v === 'ru' ? 'ru' : 'en');
      } catch {
        setLang('en');
      }
    }
    read();
    window.__renderLive = read;
    const onStorage = (e) => { if (e.key === 'spa_lang') read(); };
    window.addEventListener('storage', onStorage);
    const id = setInterval(read, 1000);
    return () => {
      window.removeEventListener('storage', onStorage);
      clearInterval(id);
      if (window.__renderLive === read) delete window.__renderLive;
    };
  }, []);
  return lang;
}

/* ─────────────────────────────────────────────── formatting helpers ─────────────── */
const fmtUsd0 = (v) => (v == null ? NA : '$' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 }));
const fmtUsd2 = (v) => (v == null ? NA : '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const fmtPct = (v, d = 2) => (v == null ? NA : Number(v).toFixed(d) + '%');
const fmtSigned = (v, d = 2) => (v == null ? NA : (v >= 0 ? '+' : '') + Number(v).toFixed(d) + '%');
function usdCompact(v) {
  const n = Number(v);
  if (v == null || !isFinite(n)) return NA;
  if (n >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'k';
  return '$' + n.toFixed(0);
}

async function getJson(path) {
  const r = await fetch(API + path, {
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    headers: { Accept: 'application/json' },
  });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

function daysUntil(targetDate) {
  if (!targetDate) return null;
  const t = new Date(targetDate + 'T00:00:00Z').getTime();
  const d = Math.ceil((t - Date.now()) / 86_400_000);
  return d > 0 ? d : 0;
}

/* ─────────────────────────────────────────────── presentational atoms ───────────── */
const card = {
  background: 'var(--bg-surface)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--r-lg)',
};
const mono = { fontFamily: 'var(--font-mono)' };

function Panel({ children, style }) {
  return <div style={{ ...card, padding: '24px', ...style }}>{children}</div>;
}

function Eyebrow({ children }) {
  return (
    <p style={{ ...mono, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.12em', color: 'var(--text-faint)', marginBottom: '10px' }}>
      {children}
    </p>
  );
}

function Metric({ label, value, sub, accent }) {
  return (
    <div style={{ ...card, padding: '18px 18px 16px' }}>
      <p style={{ ...mono, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-muted)', marginBottom: '8px' }}>
        {label}
      </p>
      <p style={{ ...mono, fontSize: '1.6rem', fontWeight: 700, color: accent || 'var(--text-primary)', lineHeight: 1.1 }}>
        {value}
      </p>
      {sub && <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', marginTop: '6px' }}>{sub}</p>}
    </div>
  );
}

function Ring({ value, max, label }) {
  const pct = max ? Math.max(0, Math.min(1, value / max)) : 0;
  const r = 64;
  const c = 2 * Math.PI * r;
  const dash = c * pct;
  return (
    <div style={{ position: 'relative', width: 160, height: 160, flexShrink: 0 }}>
      <svg width="160" height="160" viewBox="0 0 160 160" style={{ transform: 'rotate(-90deg)' }} aria-hidden="true">
        <circle cx="80" cy="80" r={r} fill="none" stroke="var(--border)" strokeWidth="10" />
        <circle cx="80" cy="80" r={r} fill="none" stroke="var(--data-teal)" strokeWidth="10"
          strokeLinecap="round" strokeDasharray={`${dash} ${c}`}
          style={{ transition: 'stroke-dasharray 600ms cubic-bezier(.4,0,.2,1)' }} />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ ...mono, fontSize: '2rem', fontWeight: 700, color: 'var(--data-teal)', lineHeight: 1 }}>
          {value == null ? NA : value}
        </span>
        <span style={{ ...mono, fontSize: '.8rem', color: 'var(--text-muted)' }}>/ {max}</span>
        <span style={{ fontSize: '.6875rem', color: 'var(--text-faint)', marginTop: '4px', textTransform: 'uppercase', letterSpacing: '.08em' }}>
          {label}
        </span>
      </div>
    </div>
  );
}

function Bar({ value, max, color }) {
  const pct = max ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div style={{ height: 8, borderRadius: 'var(--r-full)', background: 'var(--bg-surface-2)', overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 'var(--r-full)', transition: 'width 600ms cubic-bezier(.4,0,.2,1)' }} />
    </div>
  );
}

function Chip({ tone, children, title }) {
  const tones = {
    ok: { bg: 'rgba(52,211,153,.12)', bd: 'rgba(52,211,153,.30)', fg: 'var(--ok)' },
    warn: { bg: 'rgba(242,181,60,.12)', bd: 'rgba(242,181,60,.30)', fg: 'var(--warn)' },
    danger: { bg: 'rgba(242,109,109,.12)', bd: 'rgba(242,109,109,.30)', fg: 'var(--danger)' },
    teal: { bg: 'rgba(54,194,180,.12)', bd: 'rgba(54,194,180,.30)', fg: 'var(--data-teal)' },
    accent: { bg: 'var(--accent-bg)', bd: 'var(--accent-dim)', fg: 'var(--accent-hover)' },
    muted: { bg: 'var(--bg-surface-2)', bd: 'var(--border-strong)', fg: 'var(--text-muted)' },
  };
  const t = tones[tone] || tones.muted;
  return (
    <span title={title} style={{ ...mono, display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '.6875rem', padding: '4px 10px', borderRadius: 'var(--r-full)', background: t.bg, border: `1px solid ${t.bd}`, color: t.fg, whiteSpace: 'nowrap' }}>
      {children}
    </span>
  );
}

const HEADING = { fontSize: '1.25rem', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.3, margin: 0 };
const SUBTEXT = { fontSize: '.8125rem', color: 'var(--text-muted)', lineHeight: 1.55, marginTop: '4px' };
const INTRO = { fontSize: '.875rem', color: 'var(--text-secondary)', lineHeight: 1.6, marginTop: '6px', maxWidth: 760 };

/* Reusable section header (eyebrow + h2 + intro) */
function SectionHead({ eyebrow, title, intro }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2 style={{ ...HEADING, fontSize: '1.5rem' }}>{title}</h2>
      {intro && <p style={INTRO}>{intro}</p>}
    </div>
  );
}

/* Tiny "source / offline" badge per section */
function SourceTag({ live, lang }) {
  const tr = (k) => T[k][lang];
  return live
    ? <Chip tone="ok"><span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--ok)' }} aria-hidden="true" />{tr('live')}</Chip>
    : <Chip tone="muted">{tr('offline')}</Chip>;
}

/* ─────────────────────────────────────────────────── sleeve metadata ────────────── */
/* One-line "what is this" per sleeve id (matches CLAUDE.md Strategy Lab section). */
const SLEEVE_DESC = {
  engine_a: { en: 'Engine A — core conservative T1 lending sleeve.', ru: 'Engine A — основной консервативный T1-sleeve.' },
  engine_b: { en: 'Engine B — higher-yield carry sleeve.', ru: 'Engine B — sleeve более высокого кэрри.' },
  engine_c: { en: 'Engine C — LP / liquidity sleeve.', ru: 'Engine C — LP / sleeve ликвидности.' },
  rwa_floor: { en: 'RWA floor — zero-vol tokenized-T-bill benchmark.', ru: 'RWA floor — zero-vol бенчмарк tokenized-T-bills.' },
  rwa_sleeve: { en: 'RWA sleeve — holds tokenized T-bills, accrues the live floor rate.', ru: 'RWA sleeve — держит tokenized T-bills, накапливает живую ставку пола.' },
  variant_n: { en: 'Variant N — LRT (eETH) spot + short ETH-perp, β≈0 (hedged).', ru: 'Variant N — LRT (eETH) спот + short ETH-perp, β≈0 (хедж).' },
  variant_d: { en: 'Variant D — pure LRT, no hedge, β≈1 (directional, isolated).', ru: 'Variant D — чистый LRT, без хеджа, β≈1 (directional, изолирован).' },
  eth_lst_neutral: { en: 'eth_lst_neutral — plain LST (stETH/rETH) hedged with short perp, β≈0 (recommended ETH).', ru: 'eth_lst_neutral — обычный LST (stETH/rETH) с коротким перпом, β≈0 (рекоменд. ETH).' },
  eth_lst_staking: { en: 'eth_lst_staking — plain LST staking, directional.', ru: 'eth_lst_staking — обычный LST-стейкинг, directional.' },
  btc_lending_sleeve: { en: 'BTC lending — read-only advisory, ~0% (BTC barely borrowed on-chain).', ru: 'BTC lending — read-only advisory, ~0% (BTC почти не занимают on-chain).' },
  btc_neutral: { en: 'BTC neutral — hedged BTC research sleeve.', ru: 'BTC neutral — захеджированный BTC research-sleeve.' },
};
function sleeveDesc(id, lang) {
  const d = SLEEVE_DESC[id];
  return d ? d[lang] : (id || '').replace(/_/g, ' ');
}

/* ─────────────────────────────────────────────────────── component ──────────────── */
export default function DashboardLive() {
  const lang = useLang();
  const tr = (k) => (T[k] ? T[k][lang] : k);

  const [tab, setTab] = useState('overview');

  /* overview state */
  const [facts, setFacts] = useState(null);
  const [fleet, setFleet] = useState(null);
  const [status, setStatus] = useState(null);
  const [golive, setGolive] = useState(null);
  const [safety, setSafety] = useState(null);

  /* section state */
  const [lab, setLab] = useState(undefined);          // undefined=loading, null=offline
  const [promotion, setPromotion] = useState(undefined);
  const [tournament, setTournament] = useState(undefined);
  const [refusal, setRefusal] = useState(undefined);
  const [rwaBoard, setRwaBoard] = useState(undefined);
  const [ratesSurface, setRatesSurface] = useState(undefined);
  const [ratesOpps, setRatesOpps] = useState(undefined);
  const [ratesDecisions, setRatesDecisions] = useState(undefined);
  const [ratesTrack, setRatesTrack] = useState(undefined);
  const [exitNav, setExitNav] = useState(undefined);
  const [refusalLog, setRefusalLog] = useState(undefined);

  const [phase, setPhase] = useState('connecting'); // connecting | live | offline
  const [lastUpdated, setLastUpdated] = useState(null);

  const tabRef = useRef(tab);
  tabRef.current = tab;

  const poll = useCallback(async () => {
    /* SSOT first — it decides the global live/offline header state. */
    try {
      const fjson = await getJson('/api/ssot/facts');
      setFacts(fjson);
      setPhase('live');
      setLastUpdated(new Date());
    } catch {
      setPhase('offline');
      setFacts(null);
    }

    /* Every other surface is INDEPENDENT — a failure on one sets only its own
       state to null (offline) and never affects another section. Each is a
       best-effort fetch. We always poll Overview's enrichers; section feeds are
       polled too (cheap, read-only) so switching tabs is instant. */
    const indep = [
      ['/api/live/fleet', setFleet],
      ['/api/live/status', setStatus],
      ['/api/v1/golive', setGolive],
      ['/api/live/safety', setSafety],
      ['/api/strategy-lab', setLab],
      ['/api/strategy-lab/promotion', setPromotion],
      ['/api/tournament', setTournament],
      ['/api/refusal', setRefusal],
      ['/api/rwa-safety-board', setRwaBoard],
      ['/api/rates-desk/surface', setRatesSurface],
      ['/api/rates-desk/opportunities', setRatesOpps],
      ['/api/rates-desk/decisions?limit=40', setRatesDecisions],
      ['/api/rates-desk/track', setRatesTrack],
      ['/api/rates-desk/exit-nav', setExitNav],
      ['/api/rates-desk/refusals?limit=40', setRefusalLog],
    ];
    indep.forEach(([path, setter]) => {
      getJson(path).then((d) => setter(d)).catch(() => setter(null));
    });
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => clearInterval(id);
  }, [poll]);

  /* ── derived overview values ── */
  const f = facts || {};
  const days = f.real_track_days ?? f.track_days ?? null;
  const target = f.go_live_target ?? (phase === 'offline' ? GOLIVE_TARGET_FALLBACK : null);
  const anchor = f.evidenced_anchor ?? null;
  const gatesPass = f.golive_passed ?? null;
  const gatesTotal = f.golive_total ?? GATES_TOTAL_FALLBACK;
  const remaining = days != null ? Math.max(0, DAYS_NEEDED - days) : null;
  const targetDaysLeft = daysUntil(target);

  const ps = (status && status.paper_trading_status) || {};
  const regime = f.regime ?? ps.market_regime ?? null;

  const fl = fleet && fleet.available !== false ? fleet : null;
  const criteria = (golive && Array.isArray(golive.criteria)) ? golive.criteria : null;

  /* safety state → tone + label */
  const safe = safety && safety.available !== false ? safety : null;
  const safeState = safe ? safe.state : null;
  const safeTone = safeState === 'HARD_KILL' ? 'danger'
    : safeState === 'SOFT_DERISK' ? 'warn'
    : safeState === 'CLEAR' ? 'ok'
    : 'muted';

  const TABS = [
    ['overview', tr('tabOverview')],
    ['strategies', tr('tabStrategies')],
    ['tournament', tr('tabTournament')],
    ['desks', tr('tabDesks')],
    ['system', tr('tabSystem')],
    ['help', tr('tabHelp')],
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Paper banner */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '10px 16px', borderRadius: 'var(--r-md)', background: 'rgba(242,181,60,.10)', border: '1px solid rgba(242,181,60,.20)' }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--warn)', animation: 'pulse 3s ease-in-out infinite', flexShrink: 0 }} aria-hidden="true" />
        <span style={{ ...mono, fontSize: '.75rem', fontWeight: 600, color: 'var(--warn)', letterSpacing: '.05em' }}>{tr('paperBanner')}</span>
        <span style={{ fontSize: '.8125rem', color: 'rgba(242,181,60,.75)' }}>{tr('paperSub')}</span>
      </div>

      {/* Freshness bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {phase === 'live' ? (
            <Chip tone="ok"><span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--ok)', animation: 'pulse 3s ease-in-out infinite' }} aria-hidden="true" />{tr('live')}</Chip>
          ) : phase === 'offline' ? (
            <Chip tone="warn"><span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--warn)' }} aria-hidden="true" />{tr('snapshot')}</Chip>
          ) : (
            <Chip tone="muted">{tr('connecting')}</Chip>
          )}
          {lastUpdated && (
            <span style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-muted)' }}>
              {tr('updated')} {lastUpdated.toLocaleTimeString(lang === 'ru' ? 'ru-RU' : 'en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          )}
        </div>
        <button onClick={poll} style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-secondary)', background: 'transparent', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', padding: '6px 12px', cursor: 'pointer' }}>
          ↻ {tr('refresh')}
        </button>
      </div>

      {/* Tab bar — horizontally scrollable on mobile */}
      <div role="tablist" style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 4, borderBottom: '1px solid var(--border)' }}>
        {TABS.map(([id, label]) => {
          const active = tab === id;
          return (
            <button key={id} role="tab" aria-selected={active} onClick={() => setTab(id)}
              style={{
                ...mono, fontSize: '.8125rem', fontWeight: active ? 600 : 500, whiteSpace: 'nowrap',
                color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                background: active ? 'var(--bg-surface)' : 'transparent',
                border: '1px solid', borderColor: active ? 'var(--border-strong)' : 'transparent',
                borderBottom: active ? '2px solid var(--accent)' : '2px solid transparent',
                borderRadius: 'var(--r-sm) var(--r-sm) 0 0', padding: '9px 14px', cursor: 'pointer',
                transition: 'color 120ms var(--ease), background 120ms var(--ease)',
              }}>
              {label}
            </button>
          );
        })}
      </div>

      {/* ───────────────────────────────────── OVERVIEW ───────────────────────── */}
      {tab === 'overview' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <Panel style={{ background: 'linear-gradient(180deg, rgba(54,194,180,.06), transparent)', border: '1px solid rgba(54,194,180,.22)', padding: '28px' }}>
            <Eyebrow>{tr('heroEyebrow')}</Eyebrow>
            <div style={{ display: 'flex', gap: 28, alignItems: 'center', flexWrap: 'wrap' }}>
              <Ring value={days} max={DAYS_NEEDED} label={lang === 'ru' ? 'дней' : 'days'} />
              <div style={{ flex: 1, minWidth: 240 }}>
                <h2 style={{ ...HEADING, fontSize: '1.5rem' }}>{tr('heroTitle')}</h2>
                <p style={{ ...SUBTEXT, maxWidth: 460 }}>{tr('heroSub')}</p>
                <div style={{ marginTop: 16, marginBottom: 12 }}>
                  <Bar value={days || 0} max={DAYS_NEEDED} color="var(--data-teal)" />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10 }}>
                  <div style={{ ...card, padding: '10px 12px', background: 'var(--bg-base)' }}>
                    <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-faint)', marginBottom: 4 }}>{tr('anchor')}</p>
                    <p style={{ ...mono, fontSize: '.8125rem', color: 'var(--text-secondary)' }}>{anchor ?? NA}</p>
                  </div>
                  <div style={{ ...card, padding: '10px 12px', background: 'var(--bg-base)' }}>
                    <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-faint)', marginBottom: 4 }}>{tr('target')}</p>
                    <p style={{ ...mono, fontSize: '.8125rem', color: 'var(--data-teal)' }}>
                      {target ?? NA}
                      {targetDaysLeft != null && <span style={{ color: 'var(--text-muted)' }}> · {targetDaysLeft} {tr('daysLeft')}</span>}
                    </p>
                  </div>
                  <div style={{ ...card, padding: '10px 12px', background: 'var(--bg-base)' }}>
                    <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-faint)', marginBottom: 4 }}>{lang === 'ru' ? 'Осталось' : 'Remaining'}</p>
                    <p style={{ ...mono, fontSize: '.8125rem', color: 'var(--text-secondary)' }}>{remaining == null ? NA : `${remaining} ${tr('ofNeeded')}`}</p>
                  </div>
                </div>
              </div>
            </div>
          </Panel>

          {/* portfolio */}
          <div>
            <div style={{ marginBottom: 12 }}><h2 style={HEADING}>{tr('portfolio')}</h2></div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
              <Metric label={tr('equity')} value={fmtUsd0(f.current_equity)} sub={lang === 'ru' ? 'база $100k' : '$100k base'} />
              <Metric label={tr('apyToday')} value={fmtPct(f.apy_today_pct, 2)} accent="var(--data-teal)" sub={lang === 'ru' ? 'переменный' : 'variable'} />
              <Metric label={tr('dailyYield')} value={fmtUsd2(f.daily_yield_usd)} sub={lang === 'ru' ? 'бумажный' : 'paper'} />
              <Metric label={tr('totalReturn')} value={fmtSigned(f.total_return_pct, 2)} accent={(f.total_return_pct ?? 0) >= 0 ? 'var(--ok)' : 'var(--danger)'} />
              <Metric label={tr('regime')} value={regime ?? NA} />
              <Metric label={tr('nav')} value={fmtUsd0(f.nav)} accent="var(--data-teal)" sub={f.nav_reconciliation_ok ? (lang === 'ru' ? 'сверено ✓' : 'reconciled ✓') : undefined} />
            </div>
          </div>

          {/* go-live + safety */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
            <Panel>
              <Eyebrow>{tr('golive')}</Eyebrow>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, marginBottom: 10 }}>
                <span style={{ ...mono, fontSize: '2.5rem', fontWeight: 700, color: 'var(--warn)', lineHeight: 1 }}>{gatesPass ?? NA}</span>
                <span style={{ ...mono, fontSize: '1.1rem', color: 'var(--text-muted)', marginBottom: 4 }}>/ {gatesTotal}</span>
              </div>
              <Bar value={gatesPass || 0} max={gatesTotal} color="var(--warn)" />
              <p style={{ ...SUBTEXT, marginTop: 10 }}>{tr('goliveSub')}</p>
              {criteria && (
                <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 280, overflowY: 'auto' }}>
                  {criteria.map((c) => {
                    const st = (c.status || '').toUpperCase();
                    const tone = st === 'PASS' ? 'ok' : st === 'FAIL' ? 'danger' : 'warn';
                    const lbl = st === 'PASS' ? tr('pass') : st === 'FAIL' ? tr('fail') : tr('pending');
                    return (
                      <div key={c.name} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '.8125rem' }}>
                        <span style={{ width: 78, flexShrink: 0 }}><Chip tone={tone}>{lbl}</Chip></span>
                        <span style={{ color: st === 'PASS' ? 'var(--text-muted)' : 'var(--text-secondary)' }}>{c.name.replace(/_/g, ' ')}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </Panel>

            <Panel>
              <Eyebrow>{tr('safety')}</Eyebrow>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
                {safe ? <Chip tone={safeTone}>{safeState}</Chip> : <Chip tone="muted">{NA}</Chip>}
                {safe && safe.stale && <Chip tone="warn">stale</Chip>}
              </div>
              <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55 }}>
                {safe ? (safe.label || safe.reason || '') : tr('snapshot')}
              </p>
              <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <SafetyRung tone={safeState === 'CLEAR' ? 'muted' : 'muted'} active={false} label={tr('ladderDl')} color="var(--text-faint)" />
                <SafetyRung active={safeState === 'SOFT_DERISK'} label={tr('ladderSoft')} color="var(--warn)" />
                <SafetyRung active={safeState === 'HARD_KILL'} label={tr('ladderHard')} color="var(--danger)" />
              </div>
            </Panel>
          </div>

          {/* fleet */}
          <Panel>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <div>
                <Eyebrow>{tr('fleet')}</Eyebrow>
                <p style={{ ...SUBTEXT, marginTop: 0 }}>{tr('fleetSub')}</p>
              </div>
              {fl && (
                <Chip tone={fl.critical > 0 ? 'danger' : fl.warning > 0 ? 'warn' : 'ok'}>
                  {fl.overall_status || (fl.critical > 0 ? 'CRIT' : fl.warning > 0 ? 'WARN' : 'OK')}{fl.stale ? ' · stale' : ''}
                </Chip>
              )}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 12, marginTop: 16 }}>
              <Metric label={tr('healthy')} value={fl ? fl.healthy : NA} accent="var(--ok)" />
              <Metric label={tr('warning')} value={fl ? fl.warning : NA} accent={fl && fl.warning > 0 ? 'var(--warn)' : undefined} />
              <Metric label={tr('critical')} value={fl ? fl.critical : NA} accent={fl && fl.critical > 0 ? 'var(--danger)' : undefined} />
              <Metric label={lang === 'ru' ? 'Всего' : 'Total'} value={fl ? (fl.total ?? NA) : NA} />
            </div>
          </Panel>
        </div>
      )}

      {/* ───────────────────────────────── PARALLEL STRATEGIES ────────────────── */}
      {tab === 'strategies' && (
        <StrategiesSection lab={lab} promotion={promotion} lang={lang} tr={tr} />
      )}

      {/* ───────────────────────────────── TOURNAMENT ─────────────────────────── */}
      {tab === 'tournament' && (
        <TournamentSection tournament={tournament} lang={lang} tr={tr} />
      )}

      {/* ───────────────────────────────── RESEARCH DESKS ─────────────────────── */}
      {tab === 'desks' && (
        <DesksSection
          surface={ratesSurface} opps={ratesOpps} decisions={ratesDecisions} track={ratesTrack}
          refusal={refusal} rwaBoard={rwaBoard} exitNav={exitNav} refusalLog={refusalLog}
          lang={lang} tr={tr}
        />
      )}

      {/* ───────────────────────────────── SYSTEM ─────────────────────────────── */}
      {tab === 'system' && (
        <SystemSection fl={fl} safe={safe} safeState={safeState} safeTone={safeTone} lang={lang} tr={tr} />
      )}

      {/* ───────────────────────────────── HELP ───────────────────────────────── */}
      {tab === 'help' && <HelpSection lang={lang} tr={tr} />}
    </div>
  );
}

/* ── safety ladder rung ── */
function SafetyRung({ active, label, color }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 'var(--r-sm)', background: active ? 'rgba(242,109,109,.06)' : 'var(--bg-base)', border: `1px solid ${active ? color : 'var(--border)'}` }}>
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: active ? color : 'var(--text-faint)', flexShrink: 0, animation: active ? 'pulse 3s ease-in-out infinite' : 'none' }} aria-hidden="true" />
      <span style={{ fontSize: '.75rem', color: active ? 'var(--text-primary)' : 'var(--text-muted)', lineHeight: 1.4 }}>{label}</span>
    </div>
  );
}

/* ───────────────────────────────────── STRATEGIES SECTION ───────────────────────── */
function StrategiesSection({ lab, promotion, lang, tr }) {
  const offline = lab === null;
  const loading = lab === undefined;
  const strategies = (lab && Array.isArray(lab.strategies)) ? lab.strategies : [];
  const floor = (lab && lab.rwa_floor_pct != null) ? lab.rwa_floor_pct
    : (promotion && promotion.rwa_floor_pct != null ? promotion.rwa_floor_pct : RWA_FLOOR_FALLBACK);

  /* promotion stage by sleeve id (for the ladder column) */
  const stageById = {};
  if (promotion && Array.isArray(promotion.sleeves)) {
    promotion.sleeves.forEach((s) => { if (s && s.id) stageById[s.id] = s.stage; });
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <SectionHead eyebrow={tr('sleevesEyebrow')} title={tr('sleevesTitle')} intro={tr('sleevesIntro')} />
        <SourceTag live={!offline && !loading} lang={lang} />
      </div>

      {offline ? (
        <Panel><p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('sleevesOffline')}</p></Panel>
      ) : loading ? (
        <Panel><p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('connecting')}</p></Panel>
      ) : (
        <>
          <p style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-faint)' }}>
            {tr('floorNote')}: <span style={{ color: 'var(--data-teal)' }}>{fmtPct(floor, 2)}</span>
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 14 }}>
            {strategies.map((s) => {
              const stage = stageById[s.id];
              const beats = s.beats_rwa_floor === true;
              const excess = (s.net_apy_pct != null && floor != null) ? (s.net_apy_pct - floor) : null;
              const sharpe = (s.sharpe == null || s.killed) ? null : s.sharpe;
              return (
                <div key={s.id} style={{ ...card, padding: '18px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                    <span style={{ ...mono, fontSize: '.95rem', fontWeight: 600, color: 'var(--text-primary)' }}>{s.id}</span>
                    {s.killed
                      ? <Chip tone="muted" title={s.kill_reason || ''}>killed</Chip>
                      : stage
                        ? <Chip tone={stage === 'PAPER_CANDIDATE' ? 'teal' : stage === 'REJECT' ? 'danger' : 'muted'}>{stage}</Chip>
                        : <Chip tone="accent">advisory</Chip>}
                  </div>
                  <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', lineHeight: 1.5, minHeight: 32 }}>{sleeveDesc(s.id, lang)}</p>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, paddingTop: 8, borderTop: '1px solid var(--border)' }}>
                    <SleeveStat label={tr('sleeveApy')} value={fmtPct(s.net_apy_pct, 2)} accent="var(--data-teal)" />
                    <SleeveStat label={tr('sleeveSharpe')} value={sharpe == null ? tr('unknown') : Number(sharpe).toFixed(2)} accent={sharpe == null ? 'var(--text-muted)' : undefined} />
                    <SleeveStat label={tr('sleeveDd')} value={fmtPct(s.max_drawdown_pct, 2)} />
                    <SleeveStat label={tr('sleeveExcess')} value={fmtSigned(excess, 2)} accent={excess == null ? undefined : excess >= 0 ? 'var(--ok)' : 'var(--danger)'} />
                  </div>
                  {beats && <Chip tone="ok">{lang === 'ru' ? `обыгрывает пол ${fmtPct(floor, 1)}` : `beats ${fmtPct(floor, 1)} floor`}</Chip>}
                </div>
              );
            })}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
            <DeepLink href="/strategies" label={lang === 'ru' ? 'Все стратегии →' : 'All strategies →'} />
            <DeepLink href="/research" label={tr('deepResearch')} />
          </div>
        </>
      )}
    </div>
  );
}

function SleeveStat({ label, value, accent }) {
  return (
    <div>
      <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', marginBottom: 3 }}>{label}</p>
      <p style={{ ...mono, fontSize: '.95rem', fontWeight: 600, color: accent || 'var(--text-primary)' }}>{value}</p>
    </div>
  );
}

/* ───────────────────────────────────── TOURNAMENT SECTION ───────────────────────── */
function TournamentSection({ tournament, lang, tr }) {
  const offline = tournament === null;
  const loading = tournament === undefined;
  const mass = (tournament && tournament.mass_results) || {};
  const leaderboard = Array.isArray(mass.leaderboard) ? mass.leaderboard : [];
  const trustworthy = tournament ? tournament.trustworthy === true : false;
  const tested = mass.strategies_tested ?? null;
  const active = (tournament && tournament.tournament &&
    (tournament.tournament.shadow_active_strategies || tournament.tournament.active_strategies)) || [];

  const topN = leaderboard.slice(0, 12);

  function phaseOf(row) {
    // rank<=5 → shadow paper (matches strategy_tournament active set), else backtest
    return (row.rank != null && row.rank <= active.length) ? 'paper' : 'backtest';
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <SectionHead eyebrow={tr('tourEyebrow')} title={tr('tourTitle')} intro={tr('tourIntro')} />
        <SourceTag live={!offline && !loading} lang={lang} />
      </div>

      {offline ? (
        <Panel><p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('tourOffline')}</p></Panel>
      ) : loading ? (
        <Panel><p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('connecting')}</p></Panel>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <Chip tone={trustworthy ? 'ok' : 'warn'}>{trustworthy ? tr('tourTrust') : (lang === 'ru' ? 'не доверенный ранкинг' : 'not trustworthy yet')}</Chip>
            {tested != null && <span style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-muted)' }}>{tr('tourTested')}: {tested}</span>}
            <span style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-muted)' }}>{tr('tourPaper')}: {active.length}</span>
          </div>
          {!trustworthy && (
            <p style={{ fontSize: '.75rem', color: 'var(--warn)', lineHeight: 1.5 }}>{tr('tourNotTrust')}</p>
          )}

          <div style={{ ...card, overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '.8125rem' }}>
                <thead>
                  <tr style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-muted)', background: 'var(--bg-surface-2)' }}>
                    <th style={{ textAlign: 'left', padding: '10px 14px' }}>{tr('tourRank')}</th>
                    <th style={{ textAlign: 'left', padding: '10px 14px' }}>{tr('tourStrategy')}</th>
                    <th style={{ textAlign: 'right', padding: '10px 14px' }}>{tr('tourReturn')}</th>
                    <th style={{ textAlign: 'right', padding: '10px 14px' }}>{tr('sleeveSharpe')}</th>
                    <th style={{ textAlign: 'left', padding: '10px 14px' }}>{tr('tourPhase')}</th>
                  </tr>
                </thead>
                <tbody>
                  {topN.map((row, i) => {
                    const ph = phaseOf(row);
                    // Sharpe is degenerate under near-zero stablecoin vol → shown n/a.
                    const degenerate = row.sharpe == null || Number(row.sharpe) > 10;
                    const ret = row.net_annual_return_pct ?? row.annual_return_pct ?? null;
                    return (
                      <tr key={row.id || i} style={{ borderTop: '1px solid var(--border)' }}>
                        <td style={{ ...mono, padding: '10px 14px', color: i < 3 ? 'var(--data-teal)' : 'var(--text-muted)', fontWeight: i < 3 ? 700 : 400 }}>{row.rank ?? i + 1}</td>
                        <td style={{ ...mono, padding: '10px 14px', color: 'var(--text-primary)' }}>{(row.id || row.class || '?').replace(/_/g, ' ')}</td>
                        <td style={{ ...mono, padding: '10px 14px', textAlign: 'right', color: 'var(--ok)' }}>{fmtPct(ret, 2)}</td>
                        <td style={{ ...mono, padding: '10px 14px', textAlign: 'right', color: 'var(--text-muted)' }} title={degenerate ? (lang === 'ru' ? 'вырождается при locked-vol' : 'degenerate under locked-vol') : ''}>
                          {degenerate ? (lang === 'ru' ? 'n/a' : 'n/a') : Number(row.sharpe).toFixed(2)}
                        </td>
                        <td style={{ padding: '10px 14px' }}>
                          <Chip tone={ph === 'paper' ? 'teal' : 'muted'}>{ph === 'paper' ? 'shadow paper' : 'backtest'}</Chip>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
          <DeepLink href="/tournament" label={tr('fullTournament')} />
        </>
      )}
    </div>
  );
}

/* ───────────────────────────────────── DESKS SECTION ────────────────────────────── */
function DesksSection({ surface, opps, decisions, track, refusal, rwaBoard, exitNav, refusalLog, lang, tr }) {
  const surfaceQuotes = (surface && Array.isArray(surface.quotes)) ? surface.quotes : [];
  const oppN = (opps && Array.isArray(opps.opportunities)) ? opps.opportunities.length : null;
  const decCounts = (decisions && decisions.counts) || {};
  const trackDays = track && track.days != null ? track.days : null;
  const ratesLive = surface !== null && surface !== undefined;

  const refusalLive = refusal !== null && refusal !== undefined;
  const refUnderlyings = (refusal && Array.isArray(refusal.underlyings)) ? refusal.underlyings : [];
  const refCounts = (refusal && refusal.verdict_counts) || {};

  const rwaLive = rwaBoard !== null && rwaBoard !== undefined;
  const rwaCounts = (rwaBoard && rwaBoard.verdict_counts) || {};
  const rwaN = rwaBoard ? rwaBoard.n_assets : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <SectionHead eyebrow={tr('desksEyebrow')} title={tr('desksTitle')} intro={tr('desksIntro')} />

      {/* ★ FLAGSHIP Panel A — Exit-NAV-by-size waterfall (the centerpiece) */}
      <ExitNavPanel exitNav={exitNav} lang={lang} tr={tr} />

      {/* Rates Desk */}
      <Panel>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <h3 style={{ ...HEADING, fontSize: '1.05rem' }}>{tr('ratesTitle')}</h3>
            <Chip tone="ok">{tr('ratesVerdict')}</Chip>
          </div>
          <SourceTag live={ratesLive} lang={lang} />
        </div>
        <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: 14 }}>{tr('ratesWhat')}</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10 }}>
          <Metric label={tr('ratesSurface')} value={surfaceQuotes.length || (ratesLive ? 0 : NA)} />
          <Metric label={tr('ratesOpps')} value={oppN == null ? NA : oppN} accent="var(--data-teal)" />
          <Metric label={tr('ratesEntries')} value={decCounts.ENTRY == null ? NA : decCounts.ENTRY} accent="var(--ok)" />
          <Metric label={tr('ratesRefusals')} value={decCounts.REFUSAL == null ? NA : decCounts.REFUSAL} accent={decCounts.REFUSAL ? 'var(--danger)' : undefined} />
          <Metric label={tr('ratesTrackDays')} value={trackDays == null ? NA : `${trackDays}d`} />
        </div>
        <div style={{ marginTop: 14 }}><DeepLink href="/rates-desk" label={tr('deepRates')} inline /></div>
      </Panel>

      {/* Refusal verdicts */}
      <Panel>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
          <h3 style={{ ...HEADING, fontSize: '1.05rem' }}>{tr('refusalTitle')}</h3>
          <SourceTag live={refusalLive} lang={lang} />
        </div>
        <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: 14 }}>{tr('refusalWhat')}</p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
          <Chip tone="ok">SAFE {refCounts.SAFE ?? 0}</Chip>
          <Chip tone="warn">WATCH {refCounts.WATCH ?? 0}</Chip>
          <Chip tone="danger">REFUSE {refCounts.REFUSE ?? 0}</Chip>
          <Chip tone="muted">UNKNOWN {refCounts.UNKNOWN ?? 0}</Chip>
        </div>
        {refUnderlyings.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {refUnderlyings.slice(0, 8).map((u, i) => {
              const v = (u.verdict || '').toUpperCase();
              const tone = v === 'SAFE' ? 'ok' : v === 'WATCH' ? 'warn' : v === 'REFUSE' ? 'danger' : 'muted';
              return (
                <div key={u.symbol || i} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '.8125rem', padding: '6px 0', borderTop: i ? '1px solid var(--border)' : 'none' }}>
                  <span style={{ width: 78, flexShrink: 0 }}><Chip tone={tone}>{v || NA}</Chip></span>
                  <span style={{ ...mono, color: 'var(--text-primary)', width: 90, flexShrink: 0 }}>{u.symbol || '?'}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: '.75rem' }}>{u.group || ''}</span>
                  {u.tail_score != null && <span style={{ ...mono, marginLeft: 'auto', fontSize: '.75rem', color: 'var(--text-muted)' }}>tail {Number(u.tail_score).toFixed(3)}</span>}
                </div>
              );
            })}
          </div>
        ) : (
          <p style={{ fontSize: '.8125rem', color: 'var(--text-muted)' }}>{refusalLive ? (lang === 'ru' ? 'нет активов' : 'no underlyings') : tr('deskOffline')}</p>
        )}
      </Panel>

      {/* ★ FLAGSHIP Panel B — Public refusal log (the trust signal) */}
      <RefusalLogPanel refusalLog={refusalLog} lang={lang} tr={tr} />

      {/* BTC / ETH + RWA — two-up */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
        <Panel>
          <h3 style={{ ...HEADING, fontSize: '1.05rem', marginBottom: 8 }}>{tr('btcEthTitle')}</h3>
          <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55 }}>{tr('btcEthWhat')}</p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
            <Chip tone="muted">BTC lending ~0% · advisory</Chip>
            <Chip tone="teal">eth_lst_neutral · β≈0</Chip>
          </div>
        </Panel>

        <Panel>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <h3 style={{ ...HEADING, fontSize: '1.05rem' }}>{tr('rwaTitle')}</h3>
              <Chip tone="warn">{tr('rwaVerdict')}</Chip>
            </div>
            <SourceTag live={rwaLive} lang={lang} />
          </div>
          <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: 14 }}>{tr('rwaWhat')}</p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Chip tone="ok">LIQUID {rwaCounts.LIQUID ?? 0}</Chip>
            <Chip tone="warn">THIN {rwaCounts.THIN ?? 0}</Chip>
            <Chip tone="muted">REDEMPTION {rwaCounts.REDEMPTION_ONLY ?? 0}</Chip>
            <Chip tone="danger">UNSAFE {rwaCounts.UNSAFE ?? 0}</Chip>
          </div>
          {rwaN != null && <p style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-faint)', marginTop: 12 }}>{rwaN} {lang === 'ru' ? 'активов оценено' : 'assets assessed'}</p>}
        </Panel>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
        <DeepLink href="/structural-desk" label={tr('deepStructural')} />
        <DeepLink href="/rwa-backstop" label={tr('deepRwa')} />
        <DeepLink href="/research" label={tr('deepResearch')} />
      </div>
    </div>
  );
}

/* ───────────────────────────────────── SYSTEM SECTION ───────────────────────────── */
function SystemSection({ fl, safe, safeState, safeTone, lang, tr }) {
  const problems = (fl && Array.isArray(fl.agents)) ? fl.agents : [];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <SectionHead eyebrow={tr('sysEyebrow')} title={tr('sysTitle')} intro={tr('sysIntro')} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 16 }}>
        <Panel>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, marginBottom: 14 }}>
            <Eyebrow>{tr('fleet')}</Eyebrow>
            {fl && <Chip tone={fl.critical > 0 ? 'danger' : fl.warning > 0 ? 'warn' : 'ok'}>{fl.overall_status || 'OK'}{fl.stale ? ' · stale' : ''}</Chip>}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(90px, 1fr))', gap: 10 }}>
            <Metric label={tr('healthy')} value={fl ? fl.healthy : NA} accent="var(--ok)" />
            <Metric label={tr('warning')} value={fl ? fl.warning : NA} accent={fl && fl.warning > 0 ? 'var(--warn)' : undefined} />
            <Metric label={tr('critical')} value={fl ? fl.critical : NA} accent={fl && fl.critical > 0 ? 'var(--danger)' : undefined} />
            <Metric label={lang === 'ru' ? 'Всего' : 'Total'} value={fl ? (fl.total ?? NA) : NA} />
          </div>
          <div style={{ marginTop: 16 }}>
            <p style={{ ...mono, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', marginBottom: 8 }}>{tr('problemAgents')}</p>
            {problems.length === 0 ? (
              <p style={{ fontSize: '.8125rem', color: 'var(--ok)' }}>{fl ? tr('allHealthy') : NA}</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {problems.slice(0, 8).map((a, i) => (
                  <div key={a.name || i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '.75rem' }}>
                    <Chip tone={(a.status || '').toUpperCase().startsWith('CRIT') ? 'danger' : 'warn'}>{a.status}</Chip>
                    <span style={{ ...mono, color: 'var(--text-secondary)' }}>{a.name}</span>
                    {a.reason && <span style={{ color: 'var(--text-muted)' }}>· {a.reason}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </Panel>

        <Panel>
          <Eyebrow>{tr('ladderTitle')}</Eyebrow>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '4px 0 14px' }}>
            <span style={{ fontSize: '.8125rem', color: 'var(--text-secondary)' }}>{tr('ladderState')}:</span>
            {safe ? <Chip tone={safeTone}>{safeState}</Chip> : <Chip tone="muted">{NA}</Chip>}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <SafetyRung active={false} label={tr('ladderDl')} color="var(--text-faint)" />
            <SafetyRung active={safeState === 'SOFT_DERISK'} label={tr('ladderSoft')} color="var(--warn)" />
            <SafetyRung active={safeState === 'HARD_KILL'} label={tr('ladderHard')} color="var(--danger)" />
          </div>
          <p style={{ ...SUBTEXT, marginTop: 14 }}>
            {lang === 'ru' ? 'Детерминированная RiskPolicy v1.0 — без LLM. approved=False не переопределить.' : 'Deterministic RiskPolicy v1.0 — LLM-free. approved=False can be overridden by no one.'}
          </p>
        </Panel>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
        <DeepLink href="/system" label={tr('deepSystem')} />
        <DeepLink href="/status" label={tr('deepStatus')} />
      </div>
    </div>
  );
}

/* ───────────────────────────────────── HELP SECTION ─────────────────────────────── */
function HelpSection({ lang, tr }) {
  const items = [
    {
      t: { en: 'Overview', ru: 'Обзор' },
      b: {
        en: 'The headline track. Track days only count when a real daily-cycle log exists. Go-live needs all criteria passing for 7+ consecutive days. The paper portfolio is virtual $100k — no real capital.',
        ru: 'Главный трек. Дни трека считаются только при реальном логе дневного цикла. Go-live требует прохождения всех критериев 7+ дней подряд. Бумажный портфель — виртуальные $100k, реального капитала нет.',
      },
    },
    {
      t: { en: 'Parallel strategies = ADVISORY', ru: 'Параллельные стратегии = ADVISORY' },
      b: {
        en: 'These sleeves run with NO capital, only to compare ideas honestly against a real RWA floor. They never open live positions. Sharpe shows UNKNOWN until a track is ~30 days deep — that is honesty, not a missing number.',
        ru: 'Эти sleeve’ы работают БЕЗ капитала, лишь чтобы честно сравнить идеи против реального RWA-пола. Они не открывают live-позиций. Sharpe — UNKNOWN, пока трек не накопит ~30 дней — это честность, а не пропущенное число.',
      },
    },
    {
      t: { en: 'Tournament = BACKTEST ranking', ru: 'Турнир = BACKTEST-ранжирование' },
      b: {
        en: 'A deterministic backtest ranks strategies by net return. It is flagged not-trustworthy until it runs on real history. Sharpe reads n/a where it degenerates under near-zero stablecoin volatility.',
        ru: 'Детерминированный backtest ранжирует стратегии по net-доходности. Помечен как не доверенный, пока не работает на реальной истории. Sharpe = n/a там, где он вырождается при почти нулевой волатильности стейблов.',
      },
    },
    {
      t: { en: 'Research desks = REFUSAL-FIRST', ru: 'Research desks = REFUSAL-FIRST' },
      b: {
        en: 'The edge is honest measurement: harvest genuine carry, REFUSE tail-risk dressed as yield. We publish what we refuse, not only what we trade. Rates Desk is a validated GO (live in paper); RWA is measurement-GO; BTC is honestly ~0%.',
        ru: 'Edge — честное измерение: харвестить реальный carry, ОТКАЗЫВАТЬСЯ от хвостового риска под видом доходности. Публикуем отказы, не только сделки. Rates Desk — валидированный GO (live в paper); RWA — measurement-GO; BTC — честно ~0%.',
      },
    },
    {
      t: { en: 'System = the autonomous fleet', ru: 'Система = автономный парк' },
      b: {
        en: 'launchd agents run the daily cycle, monitors and autopush. The safety ladder is deterministic: drift-watch at 2%, soft de-risk at 5% (halt new allocations), hard kill at 10% (all to cash).',
        ru: 'launchd-агенты держат дневной цикл, мониторы и автопуш. Лестница защиты детерминирована: drift-watch при 2%, soft de-risk при 5% (стоп новых аллокаций), hard kill при 10% (всё в кэш).',
      },
    },
    {
      t: { en: 'Live vs offline', ru: 'Live vs офлайн' },
      b: {
        en: 'Each section polls its own endpoint every 15s. A green “Live” badge means fresh data; “Offline” / “—” means that one endpoint is unreachable — it never fabricates a number and never breaks the other sections.',
        ru: 'Каждая секция опрашивает свой endpoint каждые 15с. Зелёный «Live» — свежие данные; «Офлайн» / «—» — этот endpoint недоступен; число не выдумывается и другие секции не ломаются.',
      },
    },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <SectionHead eyebrow={tr('helpEyebrow')} title={tr('helpTitle')} intro={tr('helpIntro')} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 14 }}>
        {items.map((it, i) => (
          <div key={i} style={{ ...card, padding: '18px', borderLeft: '3px solid var(--accent)' }}>
            <h3 style={{ ...mono, fontSize: '.875rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>{it.t[lang]}</h3>
            <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>{it.b[lang]}</p>
          </div>
        ))}
      </div>
      <Panel style={{ background: 'var(--accent-bg)', border: '1px solid var(--accent-dim)' }}>
        <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          {lang === 'ru'
            ? 'Это исследовательский проект и публичный лабораторный журнал — не фонд. Капитал не привлекается, депозитов нет. Каждая цифра доходности — бумажная / переменная / не гарантирована. Не инвестиционный совет.'
            : 'This is a research project and a public lab notebook — not a fund. No capital is raised, no deposits. Every yield figure is paper / variable / not guaranteed. Not investment advice.'}
        </p>
      </Panel>
    </div>
  );
}

/* ═══════════════════════════════════ FLAGSHIP A — EXIT-NAV WATERFALL ════════════════════════════
 * A horizontal stepped waterfall (pure divs, no chart lib). x = ticket ($100K→$10M); each bar's
 * height = net proceeds as % of gross; the haircut is a --danger sliver shaded on top. Monotonic
 * descent IS the visual proof of a conservative model. Depth-limited (flagged) tickets render a
 * hatched bar with net = "—" — never a fabricated number.
 * ─────────────────────────────────────────────────────────────────────────────────────────────── */
function tickLabel(usd) {
  const n = Number(usd);
  if (!isFinite(n)) return NA;
  if (n >= 1e6) return '$' + (n / 1e6).toFixed(n % 1e6 === 0 ? 0 : 1) + 'M';
  if (n >= 1e3) return '$' + Math.round(n / 1e3) + 'K';
  return '$' + n;
}

function Waterfall({ schedule, lang, tr }) {
  const rows = Array.isArray(schedule) ? schedule : [];
  if (rows.length === 0) return null;
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'stretch', overflowX: 'auto', paddingBottom: 4 }}>
      {rows.map((r, i) => {
        const flagged = r.flagged === true || r.net_proceeds_usd == null;
        const gross = Number(r.gross_usd) || 0;
        const net = flagged ? null : Number(r.net_proceeds_usd);
        const netFrac = (!flagged && gross > 0) ? Math.max(0, Math.min(1, net / gross)) : 0;
        const haircutPct = (!flagged && r.haircut_pct != null) ? Number(r.haircut_pct) : null;
        const tte = r.time_to_exit_days;
        const COL_H = 132; // px column height for the 0–100% bar
        const netH = Math.round(netFrac * COL_H);
        return (
          <div key={r.ticket_usd || i} style={{ flex: '1 1 0', minWidth: 92, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
            {/* the stacked bar */}
            <div style={{ position: 'relative', width: '100%', maxWidth: 64, height: COL_H, borderRadius: 'var(--r-sm)', background: 'var(--bg-base)', border: '1px solid var(--border)', overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
              {flagged ? (
                /* hatched depth-limited bar — visible hole, never a fake fill */
                <div title={tr('exitDepthLimited')} style={{ position: 'absolute', inset: 0, backgroundImage: 'repeating-linear-gradient(45deg, var(--bg-surface-2) 0, var(--bg-surface-2) 5px, transparent 5px, transparent 10px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <span style={{ ...mono, fontSize: '.625rem', color: 'var(--text-faint)', transform: 'rotate(-90deg)', whiteSpace: 'nowrap', letterSpacing: '.04em' }}>{tr('exitDepthLimited')}</span>
                </div>
              ) : (
                <>
                  {/* haircut sliver (danger) above the net portion */}
                  <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: COL_H - netH, background: 'rgba(242,109,109,.16)', borderBottom: '1px dashed rgba(242,109,109,.45)' }} />
                  {/* net proceeds (teal) */}
                  <div style={{ width: '100%', height: netH, background: 'linear-gradient(180deg, var(--data-teal), rgba(54,194,180,.55))', transition: 'height 600ms cubic-bezier(.4,0,.2,1)' }} />
                </>
              )}
            </div>
            {/* x-axis ticket label */}
            <span style={{ ...mono, fontSize: '.6875rem', fontWeight: 600, color: 'var(--text-primary)' }}>{tickLabel(r.ticket_usd)}</span>
            {/* net $ / haircut % / time-to-exit */}
            <div style={{ textAlign: 'center', lineHeight: 1.5 }}>
              <p style={{ ...mono, fontSize: '.6875rem', color: flagged ? 'var(--text-faint)' : 'var(--data-teal)' }}>
                {flagged ? NA : usdCompact(net)}
              </p>
              <p style={{ ...mono, fontSize: '.625rem', color: haircutPct == null ? 'var(--text-faint)' : 'var(--danger)' }}>
                {haircutPct == null ? NA : '−' + haircutPct.toFixed(1) + '%'}
              </p>
              <p style={{ ...mono, fontSize: '.5625rem', color: 'var(--text-faint)' }}>
                {tte == null ? NA : tte + 'd'}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ExitNavPanel({ exitNav, lang, tr }) {
  const offline = exitNav === null;
  const loading = exitNav === undefined;
  const il = (exitNav && exitNav.illustrative) || null;
  const liveSchedule = (exitNav && Array.isArray(exitNav.schedule)) ? exitNav.schedule : [];
  const liveBook = (exitNav && exitNav.book) || null;
  const liveAllFlagged = liveSchedule.length > 0 && liveSchedule.every((r) => r.flagged === true || r.net_proceeds_usd == null);
  const liveGross = liveBook && liveBook.gross_usd != null ? liveBook.gross_usd : null;

  // Main visual = the illustrative schedule (so the engine is visible). If no illustrative exists,
  // fall back to the live schedule itself (honest holes).
  const mainSchedule = il && Array.isArray(il.schedule) ? il.schedule : liveSchedule;
  const mainIsIllustrative = !!(il && Array.isArray(il.schedule) && il.schedule.length);

  return (
    <Panel>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <h3 style={{ ...HEADING, fontSize: '1.15rem' }}>{tr('exitTitle')}</h3>
          <Chip tone="warn">{tr('exitModelChip')}</Chip>
        </div>
        <SourceTag live={!offline && !loading} lang={lang} />
      </div>
      <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: 14, maxWidth: 720 }}>{tr('exitSub')}</p>

      {offline ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('exitOffline')}</p>
      ) : loading ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('connecting')}</p>
      ) : (
        <>
          {mainIsIllustrative && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
              <Chip tone="teal" title={il.basis}>
                {tr('exitIllustrative')}{il.underlying ? ` · real ${il.underlying} depth` : ''}
              </Chip>
              {il.depth_usd != null && <span style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-muted)' }}>depth {usdCompact(il.depth_usd)}</span>}
            </div>
          )}

          <Waterfall schedule={mainSchedule} lang={lang} tr={tr} />

          {mainIsIllustrative && (
            <p style={{ fontSize: '.6875rem', color: 'var(--text-faint)', lineHeight: 1.5, marginTop: 10 }}>{tr('exitIllustrativeNote')}</p>
          )}

          {/* compact honest LIVE-book line */}
          <div style={{ ...card, padding: '12px 14px', background: 'var(--bg-base)', marginTop: 14 }}>
            <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--text-faint)', marginBottom: 4 }}>{tr('exitLiveBook')}</p>
            <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              {liveAllFlagged
                ? tr('exitLiveThin').replace('{x}', liveGross != null ? usdCompact(liveGross) : NA)
                : (liveSchedule.length === 0
                    ? tr('exitLiveThin').replace('{x}', liveGross != null ? usdCompact(liveGross) : NA)
                    : (lang === 'ru'
                        ? `Live-книга ${liveGross != null ? usdCompact(liveGross) : NA} (${liveBook && liveBook.underlying ? liveBook.underlying : '—'}) — график выше иллюстративный.`
                        : `Live book ${liveGross != null ? usdCompact(liveGross) : NA} (${liveBook && liveBook.underlying ? liveBook.underlying : '—'}) — the chart above is illustrative.`))}
            </p>
          </div>

          <div style={{ marginTop: 14 }}><DeepLink href="/rates-desk" label={tr('exitMethodology')} inline /></div>
        </>
      )}
    </Panel>
  );
}

/* ═══════════════════════════════════ FLAGSHIP B — PUBLIC REFUSAL LOG ═════════════════════════════
 * Top: green integrity badge from chain.verified/head_hash → flips danger "INTEGRITY BROKEN @ seq N"
 * if verified:false (this honesty IS the trust signal). Below: a vertical feed, newest-first; each
 * card = date + underlying + REFUSE/ENTRY chip + headline + plain-language paragraph + a collapsible
 * proof line (structural_reason + driver haircuts + monospace proof_hash + chain-spec link).
 * ─────────────────────────────────────────────────────────────────────────────────────────────── */
function shortHash(h) {
  if (!h || typeof h !== 'string') return NA;
  return h.length > 12 ? h.slice(0, 4) + '…' + h.slice(-4) : h;
}

function RefusalCard({ d, lang, tr }) {
  const [open, setOpen] = useState(false);
  const isRefuse = (d.kind || '').toUpperCase() === 'REFUSAL';
  const plain = lang === 'ru' ? (d.plain_ru || d.plain_en) : (d.plain_en || d.plain_ru);
  const drivers = Array.isArray(d.drivers) ? d.drivers : [];
  return (
    <div style={{ ...card, padding: '14px 16px', background: 'var(--bg-base)', borderLeft: `3px solid ${isRefuse ? 'var(--danger)' : 'var(--ok)'}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-muted)' }}>{d.as_of || NA}</span>
        <Chip tone="muted">{d.underlying || '?'}</Chip>
        <Chip tone={isRefuse ? 'danger' : 'ok'}>{isRefuse ? 'REFUSE' : 'ENTRY'}</Chip>
        {d.shape && <span style={{ ...mono, fontSize: '.625rem', color: 'var(--text-faint)' }}>{String(d.shape).replace(/_/g, ' ')}</span>}
        <span style={{ ...mono, fontSize: '.625rem', color: 'var(--text-faint)', marginLeft: 'auto' }}>#{d.seq ?? NA}</span>
      </div>
      <p style={{ fontSize: '.8125rem', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.45, marginBottom: 6 }}>{d.headline || NA}</p>
      {plain && <p style={{ fontSize: '.75rem', color: 'var(--text-secondary)', lineHeight: 1.55 }}>{plain}</p>}

      <button onClick={() => setOpen((v) => !v)} style={{ ...mono, fontSize: '.625rem', color: 'var(--accent)', background: 'transparent', border: 'none', padding: '8px 0 0', cursor: 'pointer' }}>
        {open ? '▾ ' : '▸ '}{tr('refProof')}
      </button>
      {open && (
        <div style={{ marginTop: 8, paddingTop: 10, borderTop: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {d.structural_reason && (
            <p style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-secondary)' }}>
              <span style={{ color: 'var(--text-faint)' }}>structural_reason:</span> {d.structural_reason}
            </p>
          )}
          {drivers.length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {drivers.map((dr, i) => (
                <span key={dr.field || i} title={dr.label} style={{ ...mono, fontSize: '.625rem', padding: '3px 7px', borderRadius: 'var(--r-full)', background: 'var(--bg-surface-2)', border: '1px solid var(--border)', color: dr.field === 'total_haircut' ? 'var(--danger)' : dr.field === 'fair_yield' ? 'var(--text-muted)' : 'var(--text-secondary)' }}>
                  {dr.label}: {dr.pct ?? NA}
                </span>
              ))}
            </div>
          )}
          <p style={{ ...mono, fontSize: '.625rem', color: 'var(--text-faint)', wordBreak: 'break-all' }}>
            <span style={{ color: 'var(--text-faint)' }}>proof_hash:</span> {d.proof_hash || NA}
          </p>
          <a href="/rates-desk" style={{ ...mono, fontSize: '.625rem', color: 'var(--accent)' }}>{tr('refProofSpec')}</a>
        </div>
      )}
    </div>
  );
}

function RefusalLogPanel({ refusalLog, lang, tr }) {
  const offline = refusalLog === null;
  const loading = refusalLog === undefined;
  const chain = (refusalLog && refusalLog.chain) || null;
  const counts = (refusalLog && refusalLog.counts) || {};
  const decisions = (refusalLog && Array.isArray(refusalLog.decisions)) ? refusalLog.decisions : [];
  const verified = chain ? chain.verified === true : null;

  return (
    <Panel>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <h3 style={{ ...HEADING, fontSize: '1.15rem' }}>{tr('refLogTitle')}</h3>
        <SourceTag live={!offline && !loading} lang={lang} />
      </div>
      <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: 14, maxWidth: 720 }}>{tr('refLogSub')}</p>

      {offline ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('refLogOffline')}</p>
      ) : loading ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('connecting')}</p>
      ) : (
        <>
          {/* integrity badge — the trust signal (3-state: true→green, false→red, null/absent→neutral, never implies verified) */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 14 }}>
            {verified === true ? (
              <Chip tone="ok"><span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--ok)' }} aria-hidden="true" />{tr('refChainOk')} · head {shortHash(chain && chain.head_hash)}</Chip>
            ) : verified === false ? (
              <Chip tone="danger">{tr('refChainBroken')}{chain && chain.broken_at != null ? ` @ seq ${chain.broken_at}` : ''}</Chip>
            ) : (
              <Chip tone="muted"><span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--text-muted)' }} aria-hidden="true" />{chain ? tr('refChainUnknown') : tr('refChainUnavailable')}</Chip>
            )}
            <span style={{ ...mono, fontSize: '.6875rem', color: 'var(--ok)' }}>{counts.ENTRY ?? 0} {tr('refEntries')}</span>
            <span style={{ ...mono, fontSize: '.6875rem', color: 'var(--danger)' }}>{counts.REFUSAL ?? 0} {tr('refRefusals')}</span>
          </div>

          {/* anchoring honesty — the published head is a sliding-window mirror, not an immutable all-time commitment */}
          {verified === true && (
            <p style={{ ...mono, fontSize: '.625rem', color: 'var(--text-faint)', lineHeight: 1.5, marginBottom: 14, maxWidth: 720 }}>{tr('refHeadAnchorNote')}</p>
          )}

          {/* vertical feed, newest first (API already returns most-recent-first) */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 540, overflowY: 'auto' }}>
            {decisions.length === 0 ? (
              <p style={{ fontSize: '.8125rem', color: 'var(--text-muted)' }}>{lang === 'ru' ? 'нет решений' : 'no decisions'}</p>
            ) : (
              decisions.map((d, i) => <RefusalCard key={(d.seq ?? i) + '-' + i} d={d} lang={lang} tr={tr} />)
            )}
          </div>

          <div style={{ marginTop: 14, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
            <DeepLink href="/rates-desk" label={tr('deepRates')} />
            <DeepLink href="/research" label={tr('deepResearch')} />
          </div>
        </>
      )}
    </Panel>
  );
}

/* ── deep-link card ── */
function DeepLink({ href, label, inline }) {
  if (inline) {
    return <a href={href} style={{ color: 'var(--accent)', fontSize: '.8125rem', fontWeight: 500, fontFamily: 'var(--font-mono)' }}>{label}</a>;
  }
  return (
    <a href={href} style={{ ...card, padding: '14px 18px', color: 'var(--accent)', fontSize: '.875rem', fontWeight: 500, display: 'block', transition: 'border-color 120ms var(--ease)' }}>
      {label}
    </a>
  );
}
