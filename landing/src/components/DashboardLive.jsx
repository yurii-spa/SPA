import { useState, useEffect, useCallback, useRef, Component } from 'react';
import { TONES } from './ui/tokens.js';

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
export const T = {
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
  tabProof: { en: 'Refusals & proof', ru: 'Отказы и доказательства' },
  tabAggressive: { en: 'Aggressive Lab', ru: 'Агрессивная лаб.' },
  tabRisk: { en: 'Risk', ru: 'Риск' },
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
  fullTournament: { en: 'Browse all strategies →', ru: 'Все стратегии →' },

  /* aggressive lab (Lane 3 SURFACE — the 10-15% strategies the desk REFUSES, shown WITH the tail) */
  aggEyebrow: { en: 'Outside RiskPolicy · paper-only · advisory', ru: 'Вне RiskPolicy · только бумага · advisory' },
  aggTitle: { en: 'Aggressive Lab (advisory)', ru: 'Агрессивная лаборатория (advisory)' },
  aggBanner: {
    en: 'OUTSIDE RiskPolicy · paper-only · these are the strategies the desk REFUSES — shown with the risk that comes with the yield, for owner selection. NEVER live-allocated, NEVER on the go-live track.',
    ru: 'ВНЕ RiskPolicy · только бумага · это стратегии, которые деск ОТКЛОНЯЕТ — показаны с риском, который идёт вместе с доходностью, для выбора владельцем. НИКОГДА не аллоцируются в live, НИКОГДА не на go-live треке.',
  },
  aggIntro: {
    en: 'The desk paper-tests the 10-15% strategies it normally refuses (sUSDe delta-neutral, LRT carry, leverage loops, points farms) so you can SEE them like the tournament — but the headline yield here is RISK-COMPENSATION, not free alpha. Every row shows the tail (max drawdown, the loss replayed through the 2024-26 stress windows, and the risk class) right next to the return. Promoting one to real capital is owner-gated AND custody-gated.',
    ru: 'Деск тестирует на бумаге 10-15% стратегии, которые обычно отклоняет (sUSDe delta-neutral, LRT carry, leverage loops, points farms), чтобы вы видели их как турнир — но доходность здесь это КОМПЕНСАЦИЯ ЗА РИСК, а не бесплатная альфа. Каждая строка показывает хвост (макс. просадка, убыток в стресс-окнах 2024-26 и класс риска) рядом с доходностью. Перевод в реальный капитал гейтится владельцем И кастодиальным решением.',
  },
  aggStrategy: { en: 'Strategy', ru: 'Стратегия' },
  aggReturn: { en: 'Net return', ru: 'Net доходность' },
  aggSharpe: { en: 'Sharpe', ru: 'Sharpe' },
  aggMaxDd: { en: 'Max drawdown', ru: 'Макс. просадка' },
  aggTail: { en: 'Tail in stress', ru: 'Хвост в стрессе' },
  aggClass: { en: 'Risk class', ru: 'Класс риска' },
  aggVerdict: { en: 'Verdict', ru: 'Вердикт' },
  aggSelected: { en: 'Selected', ru: 'Выбрано' },
  aggTailNote: {
    en: 'Tail in stress = the worst one-day mark-down when this strategy is replayed through the canonical 2024-08 ETH crash / 2025-10 USDe unwind / 2026-04 rsETH depeg windows. This is the loss that comes WITH the yield.',
    ru: 'Хвост в стрессе = худшая однодневная просадка при прогоне стратегии через окна 2024-08 ETH crash / 2025-10 USDe unwind / 2026-04 rsETH depeg. Это убыток, который идёт ВМЕСТЕ с доходностью.',
  },
  aggNotTrust: {
    en: 'Forward track is THIN — this is NOT a trustworthy ranking yet. Metrics shown INSUFFICIENT_DATA / n/a where there are too few realized points (we never show a fabricated Sharpe).',
    ru: 'Форвард-трек ТОНКИЙ — это пока НЕ доверенный ранкинг. Метрики INSUFFICIENT_DATA / n/a там, где реализованных точек слишком мало (мы никогда не показываем выдуманный Sharpe).',
  },
  aggTrust: { en: 'Honest multi-metric scorecard', ru: 'Честный мульти-метрик scorecard' },
  aggSelectOff: {
    en: 'Owner selection is OFF (SPA_AGGRESSIVE_LAB_SELECT). Selection is a scaffold only — it does NOTHING to live allocation without an explicit owner + custody decision.',
    ru: 'Выбор владельца ВЫКЛ (SPA_AGGRESSIVE_LAB_SELECT). Выбор это только заготовка — он НИЧЕГО не делает с live-аллокацией без явного решения владельца + кастоди.',
  },
  aggSelectOn: {
    en: 'Owner selection is ON — strategies may be marked "for consideration". This still does NOTHING to live allocation without an explicit owner + custody decision.',
    ru: 'Выбор владельца ВКЛ — стратегии можно пометить «на рассмотрение». Это всё равно НИЧЕГО не делает с live-аллокацией без явного решения владельца + кастоди.',
  },
  aggUnavailable: {
    en: 'Scorecard not generated yet — shown honestly as unavailable. No fabricated leaderboard.',
    ru: 'Scorecard ещё не сгенерирован — честно показан как недоступный. Без выдуманного лидерборда.',
  },
  aggOffline: {
    en: 'Aggressive Lab unavailable — /api/aggressive-lab/scorecard offline.',
    ru: 'Агрессивная лаборатория недоступна — /api/aggressive-lab/scorecard офлайн.',
  },

  /* annual contrast (the owner's sales surface — 15% aggressive vs the desk's steady ~5%, dated) */
  acTitle: { en: 'What chasing 15% actually costs — vs the desk’s steady ~5%', ru: 'Сколько на самом деле стоит погоня за 15% — против стабильных ~5% деска' },
  acEyebrow: { en: 'A year, dated · advisory · paper-only', ru: 'Год, с датами · advisory · только бумага' },
  acIntro: {
    en: 'Same start date, same notional, same window for both sides. The aggressive curve is a 10–15% book the desk REFUSES (its real 2024–2026 backtest). The steady line compounds the desk’s REAL conservative-book rate — an honest baseline, not a lowballed strawman. Drawdowns are dated and labelled by event, and split into realized (real peak-to-trough in the equity) and dated stress overlay (modeled by risk shape) — never blended, never invented.',
    ru: 'Одна дата старта, один notional, одно окно для обеих сторон. Агрессивная кривая — 10–15% книга, которую деск ОТКЛОНЯЕТ (реальный бэктест 2024–2026). Стабильная линия компаундит РЕАЛЬНУЮ ставку консервативной книги — честный baseline, не заниженный. Просадки датированы и подписаны событием, разделены на realized и modeled — никогда не смешиваются.',
  },
  acStableLegend: { en: 'Steady ~5% (the desk)', ru: 'Стабильные ~5% (деск)' },
  acAggLegend: { en: 'Aggressive 15%', ru: 'Агрессивные 15%' },
  acRealizedLegend: { en: 'Realized dip (in the equity)', ru: 'Realized просадка (в equity)' },
  acModeledLegend: { en: 'Modeled stress (by risk shape)', ru: 'Modeled стресс (по shape)' },
  acStableSrc: { en: 'Steady baseline source', ru: 'Источник baseline' },
  acPickStrat: { en: 'Aggressive book', ru: 'Агрессивная книга' },
  acColCagr: { en: 'CAGR', ru: 'CAGR' },
  acColMaxDd: { en: 'Max drawdown', ru: 'Макс. просадка' },
  acColUnderwater: { en: 'Days underwater', ru: 'Дней под водой' },
  acColCost: { en: 'Cost of chasing', ru: 'Цена погони' },
  acColSide: { en: '', ru: '' },
  acAggSide: { en: 'Aggressive 15%', ru: 'Агрессивные 15%' },
  acStableSide: { en: 'Steady ~5%', ru: 'Стабильные ~5%' },
  acDdHead: { en: 'The drawdown timeline, dated', ru: 'Таймлайн просадок, с датами' },
  acDdDate: { en: 'Date', ru: 'Дата' },
  acDdEvent: { en: 'Event', ru: 'Событие' },
  acDdDepth: { en: 'Hit', ru: 'Удар' },
  acDdKind: { en: 'Kind', ru: 'Тип' },
  acRealized: { en: 'realized', ru: 'realized' },
  acModeled: { en: 'modeled', ru: 'modeled' },
  acNoRealized: { en: 'No material realized drawdown in this book’s backtest equity (it accrued smoothly — the honest answer; its tail is the dated stress overlay).', ru: 'В backtest-equity этой книги нет существенной realized просадки (она начислялась ровно — честный ответ; хвост — в modeled-overlay).' },
  acBottom: {
    en: 'Across the year, the aggressive book ends higher — that is what the headline buys. But the path is paid for in dated drawdowns. The desk’s steady book walks the same year with max-drawdown ~0% — no dated cliff to explain to a client mid-quarter. That is the trade.',
    ru: 'За год агрессивная книга заканчивает выше — это и покупает хедлайн. Но путь оплачен датированными просадками. Стабильная книга деска проходит тот же год с макс. просадкой ~0% — нечего объяснять клиенту среди квартала. Вот в чём размен.',
  },
  acProof: { en: 'proof', ru: 'proof' },
  acShareLink: { en: 'Open the shareable one-pager →', ru: 'Открыть shareable одностраничник →' },

  /* edge (WS-1.5 — the real edge surfaced) */
  tabEdge: { en: 'The edge', ru: 'Edge' },
  edgeEyebrow: { en: 'The real edge · what the owner decides on', ru: 'Реальный edge · на чём решает владелец' },
  edgeTitle: { en: 'The edge — captured carry, optimizer uplift, what we refuse', ru: 'Edge — захваченный carry, прирост оптимизатора, отказы' },
  edgeIntro: {
    en: 'Three surfaces the owner needs to SEE to decide promotion: the live captured FixedCarry paper book (and how its PnL splits vs the RWA floor), the honest optimizer A/B uplift, and the fail-closed promotion refusals. All advisory / paper — separate from the go-live $100k. Each polls its own API every 15s; a dead API shows offline / —, never a fabricated number.',
    ru: 'Три поверхности, которые владелец должен ВИДЕТЬ для решения о промоушене: живая захваченная FixedCarry бумажная книга (и как её PnL делится против RWA-пола), честный прирост оптимизатора A/B и fail-closed отказы промоушена. Всё advisory / paper — отдельно от go-live $100k. Каждая опрашивает свой API каждые 15с; мёртвый API → офлайн / —, никогда выдуманное число.',
  },

  /* captured book */
  capTitle: { en: 'Captured carry book (FixedCarry)', ru: 'Захваченная carry-книга (FixedCarry)' },
  capWhat: {
    en: 'The live FixedCarry paper sleeve: accrued carry, open books and the daily refusals. Advisory PAPER research — no real capital, separate from the go-live $100k track.',
    ru: 'Живой FixedCarry бумажный sleeve: накопленный carry, открытые книги и ежедневные отказы. Advisory PAPER-исследование — без реального капитала, отдельно от go-live $100k.',
  },
  capPaperChip: { en: 'PAPER · advisory', ru: 'PAPER · advisory' },
  capEquity: { en: 'Book equity (NAV)', ru: 'Капитал книги (NAV)' },
  capAccrued: { en: 'Accrued carry', ru: 'Накопленный carry' },
  capNetApy: { en: 'Net APY', ru: 'Net APY' },
  capOpen: { en: 'Open books', ru: 'Открытые книги' },
  capRefusalsToday: { en: 'Refusals (latest scan)', ru: 'Отказы (посл. скан)' },
  capLastTick: { en: 'Last tick', ru: 'Посл. tick' },
  capAttrTitle: { en: 'PnL attribution vs RWA floor', ru: 'Атрибуция PnL против RWA-пола' },
  capAttrSub: {
    en: 'Realized PnL split into the floor-leg (what tokenized T-bills would have earned) and the carry-leg (the residual edge above the floor). carry + floor reconciles to NAV exactly.',
    ru: 'Реализованный PnL делится на floor-leg (что заработали бы tokenized T-bills) и carry-leg (остаточный edge над полом). carry + floor точно сходится к NAV.',
  },
  capFloorLeg: { en: 'Floor leg', ru: 'Floor-leg' },
  capCarryLeg: { en: 'Carry leg (excess)', ru: 'Carry-leg (excess)' },
  capRealizedPnl: { en: 'Realized PnL', ru: 'Реализ. PnL' },
  capReconciled: { en: 'reconciles to NAV ✓', ru: 'сходится к NAV ✓' },
  capNotReconciled: { en: 'attribution unavailable', ru: 'атрибуция недоступна' },
  capThin: {
    en: 'THIN: the $ split is honest, but the risk-adjusted carry quality (Sharpe) is not trustworthy until the track is ~30 days deep.',
    ru: 'THIN: долларовый сплит честен, но risk-adjusted качество carry (Sharpe) не надёжно, пока трек не накопит ~30 дней.',
  },
  capRefused: {
    en: 'Attribution REFUSED — the series failed an integrity check (gap / duplicate / look-ahead / malformed). We show no number, not a fabricated one.',
    ru: 'Атрибуция ОТКЛОНЕНА — серия не прошла проверку целостности (gap / дубль / look-ahead / порча). Показываем отсутствие числа, а не выдуманное.',
  },
  capOffline: { en: 'Captured book unavailable — /api/captured-book offline.', ru: 'Захваченная книга недоступна — /api/captured-book офлайн.' },
  capUnavailable: { en: 'Captured FixedCarry book not yet generated — the rates-desk paper agent writes it each UTC day.', ru: 'Захваченная FixedCarry книга ещё не сгенерирована — rates-desk paper-агент пишет её каждый UTC-день.' },

  /* optimizer A/B */
  optTitle: { en: 'Optimizer A/B uplift', ru: 'Прирост оптимизатора A/B' },
  optWhat: {
    en: 'Legacy risk_adjusted heuristic vs the WS-1.2 optimized_yield optimizer, replayed over the REAL evidenced live-APY window. The owner needs to SEE this to decide promotion.',
    ru: 'Legacy risk_adjusted эвристика против WS-1.2 optimized_yield оптимизатора, реплей по РЕАЛЬНОМУ подтверждённому окну live-APY. Владелец должен ВИДЕТЬ это для решения о промоушене.',
  },
  optUplift: { en: 'Risk-adjusted uplift', ru: 'Risk-adjusted прирост' },
  optLegacy: { en: 'Legacy (yield-on-deployed)', ru: 'Legacy (yield-on-deployed)' },
  optOptimized: { en: 'Optimized (yield-on-deployed)', ru: 'Optimized (yield-on-deployed)' },
  optWindow: { en: 'Replay window', ru: 'Окно реплея' },
  optCapDiag: { en: 'Cap-binding diagnostics', ru: 'Диагностика cap-binding' },
  optDaysUplift: { en: 'days uplift materialised', ru: 'дней прирост реализован' },
  optDaysBound: { en: 'days caps fully bound', ru: 'дней caps полностью связаны' },
  optBehindFlag: { en: 'behind flag · NOT cycle default', ru: 'за флагом · НЕ дефолт цикла' },
  optCaveat: { en: 'Honest caveat', ru: 'Честная оговорка' },
  optOffline: { en: 'Optimizer A/B unavailable — /api/optimizer-ab offline.', ru: 'Оптимизатор A/B недоступен — /api/optimizer-ab офлайн.' },
  optUnavailable: { en: 'Optimizer A/B artifact not yet generated.', ru: 'Артефакт оптимизатора A/B ещё не сгенерирован.' },

  /* tournament / promotion refusals */
  promoTitle: { en: 'Promotion refusals (fail-closed)', ru: 'Отказы промоушена (fail-closed)' },
  promoWhat: {
    en: 'The deterministic promotion engine REJECTS every sleeve that does not clear the RWA floor risk-adjusted — with the plain reason. Plus the tournament-trust verdict: a Sharpe leaderboard on near-zero stablecoin vol is degenerate, so it is flagged not-trustworthy. Distinct from the per-underlying rates-desk refusals.',
    ru: 'Детерминированный движок промоушена ОТКЛОНЯЕТ каждый sleeve, который не проходит RWA-пол risk-adjusted — с простой причиной. Плюс вердикт доверия турниру: Sharpe-лидерборд при почти нулевой волатильности стейблов вырожден, поэтому помечен как не доверенный. Отличается от отказов rates-desk по активам.',
  },
  promoTrustGate: { en: 'Tournament trust gate', ru: 'Гейт доверия турниру' },
  promoNotTrust: { en: 'NOT TRUSTWORTHY', ru: 'НЕ ДОВЕРЕННЫЙ' },
  promoTrust: { en: 'TRUSTWORTHY', ru: 'ДОВЕРЕННЫЙ' },
  promoCandidates: { en: 'Promotion candidates', ru: 'Кандидаты промоушена' },
  promoRejected: { en: 'Rejected (with reason)', ru: 'Отклонены (с причиной)' },
  promoOffline: { en: 'Promotion verdicts unavailable — /api/strategy-lab/promotion offline.', ru: 'Вердикты промоушена недоступны — /api/strategy-lab/promotion офлайн.' },

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
  deepPor: { en: 'Proof of Reserves →', ru: 'Доказательство резервов →' },
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
  deepExitNav: { en: 'Full exit-NAV page →', ru: 'Полная страница exit-NAV →' },
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
  deepRefusals: { en: 'Full refusal log →', ru: 'Полный лог отказов →' },
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

  /* day-30 readiness (overview) */
  day30Title: { en: 'Day-30 readiness', ru: 'Готовность к 30 дням' },
  day30Sub: {
    en: 'The deterministic 30-day artifact: evidenced days, realized return / drawdown, and the honest verdict. Risk-adjusted metrics stay THIN until ~20 returns exist.',
    ru: 'Детерминированный 30-дневный артефакт: подтверждённые дни, реализованная доходность / просадка и честный вердикт. Risk-adjusted метрики остаются THIN, пока нет ~20 доходностей.',
  },
  day30Verdict: { en: 'Verdict', ru: 'Вердикт' },
  day30Ready: { en: 'Day-30 readiness', ru: 'Готовность к 30д' },
  day30Realized: { en: 'Realized return', ru: 'Реализ. доходность' },
  day30Dd: { en: 'Realized max DD', ru: 'Реализ. макс. DD' },
  day30Sharpe: { en: 'Sharpe (THIN)', ru: 'Sharpe (THIN)' },
  day30Offline: { en: 'Day-30 artifact unavailable — /api/v1/day30 offline.', ru: 'Артефакт 30 дней недоступен — /api/v1/day30 офлайн.' },

  /* risk section */
  riskEyebrow: { en: 'Deterministic safety · LLM-free', ru: 'Детерминированная защита · без LLM' },
  riskTitle: { en: 'Risk & cutover readiness', ru: 'Риск и готовность к cutover' },
  riskIntro: {
    en: 'The deterministic two-tier safety ladder that governs the book (RiskPolicy v1.0, no LLM), the live drawdown position on it, plus the honest cutover scorecard and our own adversarial red-team verdict. Each panel polls its own API; a dead API shows offline / —, never a fabricated PASS.',
    ru: 'Детерминированная двухуровневая лестница защиты, управляющая портфелем (RiskPolicy v1.0, без LLM), живая позиция просадки на ней, плюс честный scorecard cutover и наш собственный adversarial red-team вердикт. Каждая панель опрашивает свой API; мёртвый API → офлайн / —, никогда выдуманный PASS.',
  },
  ladderVizTitle: { en: 'Kill-switch ladder (two-tier)', ru: 'Лестница kill-switch (два уровня)' },
  ladderVizSub: {
    en: 'Four deterministic rungs from drawdown. DL-01 (daily-loss 2%) and DL-02 (peak-to-trough 10%) HALT allocation; SOFT de-risk (5%) halts new allocations; HARD kill (10%) moves all to cash. The marker shows the live drawdown — approved=False cannot be overridden by anyone.',
    ru: 'Четыре детерминированных ступени по просадке. DL-01 (дневной убыток 2%) и DL-02 (peak-to-trough 10%) HALT аллокации; SOFT de-risk (5%) стоп новых аллокаций; HARD kill (10%) всё в кэш. Маркер показывает живую просадку — approved=False никто не может переопределить.',
  },
  ladderCurrentDd: { en: 'Live drawdown', ru: 'Живая просадка' },
  ladderRungDl1: { en: 'DL-01 · daily loss', ru: 'DL-01 · дневной убыток' },
  ladderRungSoft: { en: 'SOFT de-risk', ru: 'SOFT de-risk' },
  ladderRungHard: { en: 'HARD kill', ru: 'HARD kill' },
  ladderRungDl2: { en: 'DL-02 · peak DD', ru: 'DL-02 · peak DD' },
  ladderDl1Action: { en: 'HALT allocation (daily loss)', ru: 'HALT аллокации (дневной убыток)' },
  ladderSoftAction: { en: 'halt NEW allocations, hold book', ru: 'стоп НОВЫХ аллокаций, держим книгу' },
  ladderHardAction: { en: 'all to cash', ru: 'всё в кэш' },
  ladderDl2Action: { en: 'HALT allocation (peak drawdown)', ru: 'HALT аллокации (peak просадка)' },
  ladderGovOffline: { en: 'Governance policy unavailable — /api/governance offline; ladder thresholds shown from the canonical RiskPolicy literals.', ru: 'Политика governance недоступна — /api/governance офлайн; пороги лестницы показаны из канонических литералов RiskPolicy.' },
  ladderSafetyOffline: { en: 'Live safety state unavailable — /api/live/safety offline; the marker is hidden (no fabricated position).', ru: 'Живое состояние защиты недоступно — /api/live/safety офлайн; маркер скрыт (без выдуманной позиции).' },
  govPosture: { en: 'Dual-control posture', ru: 'Состояние dual-control' },
  govEnforced: { en: 'enforced', ru: 'включено' },
  govAdvisory: { en: 'advisory (paper)', ru: 'advisory (paper)' },

  /* execution readiness */
  execTitle: { en: 'Cutover readiness scorecard', ru: 'Scorecard готовности к cutover' },
  execWhat: {
    en: 'The honest CODE-readiness scorecard. Code-readiness is NOT go-live: the owner-only blockers (custody, real capital, audit, 30-day track, the owner-gated is_live flip) are named plainly and gate everything. This endpoint only reports — it cannot flip live.',
    ru: 'Честный scorecard CODE-готовности. CODE-готовность — НЕ go-live: owner-only блокеры (custody, реальный капитал, аудит, 30-дневный трек, owner-gated is_live флип) названы прямо и гейтят всё. Этот endpoint только сообщает — он не может включить live.',
  },
  execCodeReady: { en: 'Code-readiness', ru: 'CODE-готовность' },
  execPosture: { en: 'Posture', ru: 'Состояние' },
  execReadyForLive: { en: 'Ready for live', ru: 'Готово к live' },
  execChecks: { en: 'Code defenses', ru: 'Code-защиты' },
  execOwnerBlockers: { en: 'Owner-only blockers (off-code — gate go-live)', ru: 'Owner-only блокеры (вне кода — гейтят go-live)' },
  execNotGoLive: { en: 'CODE-readiness ≠ go-live (owner-gated)', ru: 'CODE-готовность ≠ go-live (owner-gated)' },
  execOffline: { en: 'Cutover scorecard unavailable — /api/execution/readiness offline.', ru: 'Scorecard cutover недоступен — /api/execution/readiness офлайн.' },

  /* red-team */
  redTitle: { en: 'We red-team ourselves', ru: 'Мы red-team’им сами себя' },
  redWhat: {
    en: 'A standing adversarial harness tries to break our own integrity / safety surfaces. The verdict carries an anchored report hash so the claim is itself verifiable — you can re-derive it. Fail-closed: no published run reads as "no red-team yet", never as a silent PASS.',
    ru: 'Постоянный adversarial harness пытается сломать наши собственные поверхности целостности / защиты. Вердикт несёт привязанный хеш отчёта, поэтому само заявление проверяемо — его можно пересчитать. Fail-closed: отсутствие прогона читается как «red-team ещё не было», а не как молчаливый PASS.',
  },
  redVerdict: { en: 'Verdict', ru: 'Вердикт' },
  redPass: { en: 'ALL CAUGHT', ru: 'ВСЁ ПОЙМАНО' },
  redFail: { en: 'ESCAPED', ru: 'ПРОРВАЛОСЬ' },
  redScenarios: { en: 'Scenarios', ru: 'Сценарии' },
  redCaught: { en: 'Caught', ru: 'Поймано' },
  redEscaped: { en: 'Escaped', ru: 'Прорвалось' },
  redLiveUntouched: { en: 'Live data untouched', ru: 'Live-данные не тронуты' },
  redReportHash: { en: 'Anchored report hash', ru: 'Привязанный хеш отчёта' },
  redNone: { en: 'No red-team run published yet — fail-closed (we never imply a pass we did not run).', ru: 'Прогон red-team ещё не опубликован — fail-closed (мы не подразумеваем pass, которого не было).' },
  redOffline: { en: 'Red-team verdict unavailable — /api/redteam offline.', ru: 'Red-team вердикт недоступен — /api/redteam офлайн.' },

  /* proof section */
  proofEyebrow: { en: 'Don’t trust us · check us', ru: 'Не верьте нам · проверьте нас' },
  proofTitle: { en: 'Refusals & proof', ru: 'Отказы и доказательства' },
  proofIntro: {
    en: 'The credibility surface: every declined trade with a tamper-evident proof, the rates-desk proof chain, the per-underlying refusal verdicts, the fail-closed promotion refusals, and our own red-team verdict. We publish what we refuse, not only what we trade — and you can re-derive every hash yourself.',
    ru: 'Поверхность доверия: каждая отклонённая сделка с защищённым от подмены доказательством, proof-цепочка rates-desk, вердикты отказа по активам, fail-closed отказы промоушена и наш собственный red-team вердикт. Мы публикуем отказы, а не только сделки — и каждый хеш можно пересчитать самому.',
  },
  proofVerifyCta: { en: 'Verify it yourself → /verify (one command, <5 min)', ru: 'Проверьте сами → /verify (одна команда, <5 мин)' },

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
  // Converged onto the ONE canonical tone map (ui/tokens.js TONES) — was a local hardcoded
  // rgba map that DIVERGED from the tokens (Sprint-0 Lane B convergence). Every tone now
  // resolves to the same CSS custom properties every other surface (Badge/StatusPill/cockpit) uses.
  const t = TONES[tone] || TONES.muted;
  return (
    <span title={title} style={{ ...mono, display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '.6875rem', padding: '4px 10px', borderRadius: 'var(--r-full)', background: t.bg, border: `1px solid ${t.border}`, color: t.fg, whiteSpace: 'nowrap' }}>
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

/* ───────────────────────────────────────── per-panel error boundary ─────────────── */
/* A render-time exception inside one tab/section must NOT blank the whole command
 * center. Each tab's content is wrapped in this boundary, so a crash degrades to a
 * single honest error card for THAT panel and the rest of the page + chrome render fine.
 * (React error boundaries must be class components — there is no hook equivalent.) */
class PanelBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    // Surface to the console for debugging; never rethrow (that would re-blank the page).
    if (typeof console !== 'undefined' && console.error) {
      console.error('[DashboardLive] panel render error:', error, info);
    }
  }
  render() {
    if (this.state.error) {
      const ru = this.props.lang === 'ru';
      return (
        <div style={{ ...card, padding: '20px', borderLeft: '3px solid var(--danger)', background: 'rgba(242,109,109,.06)' }}>
          <p style={{ ...mono, fontSize: '.6875rem', textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--danger)', marginBottom: 8 }}>
            {ru ? 'Эта панель не отрисовалась' : 'This panel failed to render'}
          </p>
          <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55 }}>
            {ru
              ? 'Произошла ошибка отображения в этой секции. Остальная часть дашборда работает. Обновите страницу, чтобы попробовать снова.'
              : 'A display error occurred in this section. The rest of the dashboard is unaffected. Reload the page to try again.'}
          </p>
          <p style={{ ...mono, fontSize: '.625rem', color: 'var(--text-faint)', marginTop: 8, wordBreak: 'break-word' }}>
            {String(this.state.error && this.state.error.message || this.state.error)}
          </p>
        </div>
      );
    }
    return this.props.children;
  }
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
  /* WS-1.5 — the real-edge surfaces (each polls its OWN endpoint, honest LIVE/offline per-panel) */
  const [capturedBook, setCapturedBook] = useState(undefined);
  const [optimizerAb, setOptimizerAb] = useState(undefined);
  /* WS-7 — risk / cutover / proof surfaces (each polls its OWN endpoint, honest LIVE/offline) */
  const [governance, setGovernance] = useState(undefined);
  const [execRead, setExecRead] = useState(undefined);
  const [redteam, setRedteam] = useState(undefined);
  const [day30, setDay30] = useState(undefined);
  /* Aggressive Lab (Lane 3 SURFACE) — advisory/paper-only ranking of the strategies the desk REFUSES */
  const [aggressive, setAggressive] = useState(undefined);
  /* Annual Contrast (the owner's sales surface — 15% aggressive vs the steady ~5%, dated) */
  const [contrast, setContrast] = useState(undefined);

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
      ['/api/captured-book', setCapturedBook],
      ['/api/optimizer-ab', setOptimizerAb],
      ['/api/governance', setGovernance],
      ['/api/execution/readiness', setExecRead],
      ['/api/redteam', setRedteam],
      ['/api/v1/day30', setDay30],
      ['/api/aggressive-lab/scorecard', setAggressive],
      ['/api/aggressive-lab/annual-contrast', setContrast],
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

  /* SLO: how many of the polled public surfaces are reachable right now (live=non-null & not loading).
     Honest uptime read — never claims a surface is live when its fetch failed. */
  const surfaceStates = [
    facts, fleet, status, golive, safety, lab, promotion, tournament, refusal, rwaBoard,
    ratesSurface, ratesOpps, ratesDecisions, ratesTrack, exitNav, refusalLog,
    capturedBook, optimizerAb, governance, execRead, redteam, day30, aggressive, contrast,
  ];
  const surfacesTotal = surfaceStates.length;
  const surfacesLive = surfaceStates.filter((s) => s != null).length;

  /* Unified desk console — five coherent sections + research desks + legend.
     The Edge folds in the parallel-strategy sleeves and the tournament leaderboard so
     "what is the edge" lives in one place; Refusals & proof is the dedicated trust surface;
     Risk carries the kill-switch ladder + cutover scorecard + red-team. */
  const TABS = [
    ['overview', tr('tabOverview')],
    ['edge', tr('tabEdge')],
    ['proof', tr('tabProof')],
    ['aggressive', tr('tabAggressive')],
    ['risk', tr('tabRisk')],
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

      {/* Freshness / SLO bar — global live state + how many of the public surfaces are reachable.
          aria-live=polite so a screen reader announces a live↔offline flip; aria-atomic keeps it whole. */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}
        role="status" aria-live="polite" aria-atomic="true">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {phase === 'live' ? (
            <Chip tone="ok"><span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--ok)', animation: 'pulse 3s ease-in-out infinite' }} aria-hidden="true" />{tr('live')}</Chip>
          ) : phase === 'offline' ? (
            <Chip tone="warn"><span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--warn)' }} aria-hidden="true" />{tr('snapshot')}</Chip>
          ) : (
            <Chip tone="muted">{tr('connecting')}</Chip>
          )}
          {/* SLO: reachable surfaces / total polled — honest per-surface uptime read */}
          {surfacesTotal > 0 && (
            <Chip tone={surfacesLive === surfacesTotal ? 'ok' : surfacesLive === 0 ? 'danger' : 'warn'}
              title={lang === 'ru' ? 'Сколько публичных API-поверхностей сейчас отвечают' : 'How many public API surfaces are currently responding'}>
              {surfacesLive}/{surfacesTotal} {lang === 'ru' ? 'поверхностей' : 'surfaces'}
            </Chip>
          )}
          {lastUpdated && (
            <span style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-muted)' }}>
              {tr('updated')} {lastUpdated.toLocaleTimeString(lang === 'ru' ? 'ru-RU' : 'en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          )}
        </div>
        <button onClick={poll} aria-label={tr('refresh')} style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-secondary)', background: 'transparent', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', padding: '6px 12px', cursor: 'pointer' }}>
          ↻ {tr('refresh')}
        </button>
      </div>

      {/* Tab bar — horizontally scrollable on mobile. a11y: roving tabindex + arrow-key nav,
          aria-controls binds each tab to its panel; the active panel has role=tabpanel below. */}
      <div role="tablist" aria-label={lang === 'ru' ? 'Разделы консоли' : 'Console sections'}
        style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 4, borderBottom: '1px solid var(--border)' }}
        onKeyDown={(e) => {
          if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft' && e.key !== 'Home' && e.key !== 'End') return;
          e.preventDefault();
          const idx = TABS.findIndex(([id]) => id === tab);
          let next = idx;
          if (e.key === 'ArrowRight') next = (idx + 1) % TABS.length;
          else if (e.key === 'ArrowLeft') next = (idx - 1 + TABS.length) % TABS.length;
          else if (e.key === 'Home') next = 0;
          else if (e.key === 'End') next = TABS.length - 1;
          const nextId = TABS[next][0];
          setTab(nextId);
          const el = document.getElementById('tab-' + nextId);
          if (el) el.focus();
        }}>
        {TABS.map(([id, label]) => {
          const active = tab === id;
          return (
            <button key={id} id={'tab-' + id} role="tab" aria-selected={active}
              aria-controls={'panel-' + id} tabIndex={active ? 0 : -1} onClick={() => setTab(id)}
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
        <PanelBoundary lang={lang}>
        <div id="panel-overview" role="tabpanel" aria-labelledby="tab-overview" tabIndex={0} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
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

          {/* day-30 readiness */}
          <Day30Panel day30={day30} lang={lang} tr={tr} />

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
        </PanelBoundary>
      )}

      {/* ─────────────────────── THE EDGE (WS-1.5 + sleeves + tournament) ──────── */}
      {tab === 'edge' && (
        <PanelBoundary lang={lang}>
          <div id="panel-edge" role="tabpanel" aria-labelledby="tab-edge" tabIndex={0} style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
            <EdgeSection
              capturedBook={capturedBook} optimizerAb={optimizerAb} promotion={promotion}
              lang={lang} tr={tr}
            />
            <StrategiesSection lab={lab} promotion={promotion} lang={lang} tr={tr} />
            <TournamentSection tournament={tournament} lang={lang} tr={tr} />
          </div>
        </PanelBoundary>
      )}

      {/* ─────────────────────── REFUSALS & PROOF (trust surface) ──────────────── */}
      {tab === 'proof' && (
        <PanelBoundary lang={lang}>
          <div id="panel-proof" role="tabpanel" aria-labelledby="tab-proof" tabIndex={0}>
            <ProofSection
              decisions={ratesDecisions} track={ratesTrack} refusal={refusal}
              refusalLog={refusalLog} promotion={promotion} redteam={redteam}
              lang={lang} tr={tr}
            />
          </div>
        </PanelBoundary>
      )}

      {/* ─────────────────────── AGGRESSIVE LAB (advisory · OUTSIDE RiskPolicy) ── */}
      {tab === 'aggressive' && (
        <PanelBoundary lang={lang}>
          <div id="panel-aggressive" role="tabpanel" aria-labelledby="tab-aggressive" tabIndex={0}>
            <AggressiveLabSection aggressive={aggressive} contrast={contrast} lang={lang} tr={tr} />
          </div>
        </PanelBoundary>
      )}

      {/* ─────────────────────── RISK (kill-switch ladder + cutover + red-team) ── */}
      {tab === 'risk' && (
        <PanelBoundary lang={lang}>
          <div id="panel-risk" role="tabpanel" aria-labelledby="tab-risk" tabIndex={0}>
            <RiskSection
              governance={governance} safety={safe} safeState={safeState} safeTone={safeTone}
              execRead={execRead} redteam={redteam} lang={lang} tr={tr}
            />
          </div>
        </PanelBoundary>
      )}

      {/* ───────────────────────────────── RESEARCH DESKS ─────────────────────── */}
      {tab === 'desks' && (
        <PanelBoundary lang={lang}>
          <div id="panel-desks" role="tabpanel" aria-labelledby="tab-desks" tabIndex={0}>
            <DesksSection
              surface={ratesSurface} opps={ratesOpps} decisions={ratesDecisions} track={ratesTrack}
              refusal={refusal} rwaBoard={rwaBoard} exitNav={exitNav} refusalLog={refusalLog}
              lang={lang} tr={tr}
            />
          </div>
        </PanelBoundary>
      )}

      {/* ───────────────────────────────── SYSTEM ─────────────────────────────── */}
      {tab === 'system' && (
        <PanelBoundary lang={lang}>
          <div id="panel-system" role="tabpanel" aria-labelledby="tab-system" tabIndex={0}>
            <SystemSection fl={fl} safe={safe} safeState={safeState} safeTone={safeTone} lang={lang} tr={tr} />
          </div>
        </PanelBoundary>
      )}

      {/* ───────────────────────────────── HELP ───────────────────────────────── */}
      {tab === 'help' && (
        <PanelBoundary lang={lang}>
          <div id="panel-help" role="tabpanel" aria-labelledby="tab-help" tabIndex={0}>
            <HelpSection lang={lang} tr={tr} />
          </div>
        </PanelBoundary>
      )}
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

/* ═══════════════════════════════════ EDGE SECTION (WS-1.5) ═══════════════════════════════════
 * Three panels surfacing the REAL edge the owner decides on:
 *   A — Captured book (FixedCarry paper book + carry-leg/floor-leg PnL attribution → NAV).
 *   B — Optimizer A/B (the honest +1.37pp risk-adjusted uplift + the verbatim caveat + cap diag).
 *   C — Promotion refusals (fail-closed REJECTs with reasons + the tournament-trust verdict).
 * Each panel polls its OWN API; a dead/null API renders offline / — (never a fabricated number).
 * ─────────────────────────────────────────────────────────────────────────────────────────── */
function signedUsd(v) {
  if (v == null || !isFinite(Number(v))) return NA;
  const n = Number(v);
  return (n >= 0 ? '+' : '−') + '$' + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function EdgeSection({ capturedBook, optimizerAb, promotion, lang, tr }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <SectionHead eyebrow={tr('edgeEyebrow')} title={tr('edgeTitle')} intro={tr('edgeIntro')} />
      <CapturedBookPanel capturedBook={capturedBook} lang={lang} tr={tr} />
      <OptimizerAbPanel optimizerAb={optimizerAb} lang={lang} tr={tr} />
      <PromotionRefusalPanel promotion={promotion} lang={lang} tr={tr} />
    </div>
  );
}

/* ── A · Captured book + attribution ── */
function CapturedBookPanel({ capturedBook, lang, tr }) {
  const offline = capturedBook === null;
  const loading = capturedBook === undefined;
  const unavailable = capturedBook && capturedBook.status === 'unavailable';
  const live = !offline && !loading && !unavailable;
  const attr = (capturedBook && capturedBook.attribution) || null;
  const reconciles = attr && attr.reconciles === true;
  const refused = attr && attr.status === 'UNKNOWN';
  const refuseList = (capturedBook && capturedBook.refusals) || {};
  const refuseEntries = Object.entries(refuseList);

  return (
    <Panel>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <h3 style={{ ...HEADING, fontSize: '1.15rem' }}>{tr('capTitle')}</h3>
          <Chip tone="warn">{tr('capPaperChip')}</Chip>
        </div>
        <SourceTag live={live} lang={lang} />
      </div>
      <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: 14, maxWidth: 720 }}>{tr('capWhat')}</p>

      {offline ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('capOffline')}</p>
      ) : loading ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('connecting')}</p>
      ) : unavailable ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('capUnavailable')}</p>
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10 }}>
            <Metric label={tr('capEquity')} value={fmtUsd2(capturedBook.equity_usd)} accent="var(--data-teal)" />
            <Metric label={tr('capAccrued')} value={signedUsd(capturedBook.accrued_carry_usd)} accent={(capturedBook.accrued_carry_usd ?? 0) >= 0 ? 'var(--ok)' : 'var(--danger)'} />
            <Metric label={tr('capNetApy')} value={fmtPct(capturedBook.net_apy_pct, 4)} />
            <Metric label={tr('capOpen')} value={capturedBook.n_open_books == null ? NA : capturedBook.n_open_books} />
            <Metric label={tr('capLastTick')} value={capturedBook.last_tick || NA} />
          </div>

          {/* refusal reasons (latest scan) */}
          <div style={{ marginTop: 14 }}>
            <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', marginBottom: 8 }}>{tr('capRefusalsToday')}</p>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {refuseEntries.length === 0
                ? <Chip tone="muted">{NA}</Chip>
                : refuseEntries.map(([reason, n]) => (
                    <Chip key={reason} tone="danger">{String(reason).replace(/_/g, ' ')} · {n}</Chip>
                  ))}
            </div>
          </div>

          {/* PnL attribution → NAV */}
          <div style={{ ...card, padding: '16px', background: 'var(--bg-base)', marginTop: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
              <p style={{ ...mono, fontSize: '.8125rem', fontWeight: 600, color: 'var(--text-primary)' }}>{tr('capAttrTitle')}</p>
              {refused
                ? <Chip tone="danger">{tr('capNotReconciled')}</Chip>
                : reconciles
                  ? <Chip tone="ok">{tr('capReconciled')}</Chip>
                  : <Chip tone="muted">{tr('capNotReconciled')}</Chip>}
            </div>
            <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 12 }}>{tr('capAttrSub')}</p>
            {refused || !attr ? (
              <p style={{ fontSize: '.8125rem', color: 'var(--danger)', lineHeight: 1.55 }}>{tr('capRefused')}</p>
            ) : (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10 }}>
                  <SleeveStat label={tr('capFloorLeg')} value={signedUsd(attr.floor_leg_usd)} accent="var(--text-secondary)" />
                  <SleeveStat label={tr('capCarryLeg')} value={signedUsd(attr.carry_leg_usd)} accent={(attr.carry_leg_usd ?? 0) >= 0 ? 'var(--ok)' : 'var(--danger)'} />
                  <SleeveStat label={tr('capRealizedPnl')} value={signedUsd(attr.realized_pnl_usd)} accent="var(--data-teal)" />
                </div>
                {attr.thin && (
                  <p style={{ fontSize: '.6875rem', color: 'var(--warn)', lineHeight: 1.5, marginTop: 12 }}>{tr('capThin')}</p>
                )}
              </>
            )}
          </div>

          <div style={{ marginTop: 14 }}><DeepLink href="/rates-desk" label={tr('deepRates')} inline /></div>
        </>
      )}
    </Panel>
  );
}

/* ── B · Optimizer A/B uplift ── */
function OptimizerAbPanel({ optimizerAb, lang, tr }) {
  const offline = optimizerAb === null;
  const loading = optimizerAb === undefined;
  const unavailable = optimizerAb && optimizerAb.status === 'unavailable';
  const live = !offline && !loading && !unavailable;
  const cap = (optimizerAb && optimizerAb.cap_binding_diagnostics) || {};
  const caveat = optimizerAb && (optimizerAb.honest_caveat || optimizerAb.disclaimer);

  return (
    <Panel>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <h3 style={{ ...HEADING, fontSize: '1.15rem' }}>{tr('optTitle')}</h3>
          <Chip tone="muted">{tr('optBehindFlag')}</Chip>
        </div>
        <SourceTag live={live} lang={lang} />
      </div>
      <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: 14, maxWidth: 720 }}>{tr('optWhat')}</p>

      {offline ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('optOffline')}</p>
      ) : loading ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('connecting')}</p>
      ) : unavailable ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('optUnavailable')}</p>
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
            <Metric
              label={tr('optUplift')}
              value={optimizerAb.uplift_pp == null ? NA : (Number(optimizerAb.uplift_pp) >= 0 ? '+' : '') + Number(optimizerAb.uplift_pp).toFixed(2) + 'pp'}
              accent={(optimizerAb.uplift_pp ?? 0) >= 0 ? 'var(--ok)' : 'var(--danger)'}
            />
            <Metric label={tr('optLegacy')} value={fmtPct(optimizerAb.legacy_apy, 2)} />
            <Metric label={tr('optOptimized')} value={fmtPct(optimizerAb.optimized_apy, 2)} accent="var(--data-teal)" />
            <Metric label={tr('optWindow')} value={optimizerAb.n_days == null ? NA : `${optimizerAb.n_days}d`} sub={optimizerAb.window_start ? `${optimizerAb.window_start} → ${optimizerAb.window_end || '?'}` : undefined} />
          </div>

          {/* cap-binding diagnostics */}
          <div style={{ ...card, padding: '14px 16px', background: 'var(--bg-base)', marginTop: 16 }}>
            <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', marginBottom: 8 }}>{tr('optCapDiag')}</p>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Chip tone="teal">{cap.days_uplift_materialised ?? 0} / {cap.days_total ?? (optimizerAb.n_days ?? 0)} {tr('optDaysUplift')}</Chip>
              <Chip tone={cap.days_caps_fully_bound ? 'warn' : 'muted'}>{cap.days_caps_fully_bound ?? 0} {tr('optDaysBound')}</Chip>
            </div>
          </div>

          {/* HONEST caveat — verbatim from the artifact */}
          {caveat && (
            <div style={{ ...card, padding: '14px 16px', background: 'var(--accent-bg)', border: '1px solid var(--accent-dim)', borderLeft: '3px solid var(--warn)', marginTop: 14 }}>
              <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--warn)', marginBottom: 6 }}>{tr('optCaveat')}</p>
              <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>{caveat}</p>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

/* ── C · Promotion refusals (fail-closed) + tournament trust gate ── */
function PromotionRefusalPanel({ promotion, lang, tr }) {
  const offline = promotion === null;
  const loading = promotion === undefined;
  const live = !offline && !loading;
  const sleeves = (promotion && Array.isArray(promotion.sleeves)) ? promotion.sleeves : [];
  const rejected = sleeves.filter((s) => s && (s.stage === 'REJECT'));
  const candidates = sleeves.filter((s) => s && s.stage === 'PAPER_CANDIDATE');
  // tournament trust verdict travels on the mass-tournament meta; surfaced honestly fail-closed.
  const trust = promotion && promotion.tournament_trustworthy;

  return (
    <Panel>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <h3 style={{ ...HEADING, fontSize: '1.15rem' }}>{tr('promoTitle')}</h3>
        <SourceTag live={live} lang={lang} />
      </div>
      <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: 14, maxWidth: 720 }}>{tr('promoWhat')}</p>

      {offline ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('promoOffline')}</p>
      ) : loading ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('connecting')}</p>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 14 }}>
            <Chip tone="teal">{tr('promoCandidates')}: {candidates.length}</Chip>
            <Chip tone="danger">{tr('promoRejected')}: {rejected.length}</Chip>
            {trust != null && (
              <Chip tone={trust ? 'ok' : 'warn'}>{tr('promoTrustGate')}: {trust ? tr('promoTrust') : tr('promoNotTrust')}</Chip>
            )}
          </div>

          {rejected.length === 0 ? (
            <p style={{ fontSize: '.8125rem', color: 'var(--text-muted)' }}>{lang === 'ru' ? 'нет отклонённых sleeve’ов' : 'no rejected sleeves'}</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {rejected.map((s, i) => (
                <div key={s.id || i} style={{ ...card, padding: '12px 14px', background: 'var(--bg-base)', borderLeft: '3px solid var(--danger)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
                    <Chip tone="danger">{s.stage || 'REJECT'}</Chip>
                    <span style={{ ...mono, fontSize: '.8125rem', fontWeight: 600, color: 'var(--text-primary)' }}>{s.id || '?'}</span>
                  </div>
                  {s.reason && <p style={{ fontSize: '.75rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>{s.reason}</p>}
                </div>
              ))}
            </div>
          )}

          <div style={{ marginTop: 14, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
            <DeepLink href="/strategies" label={lang === 'ru' ? 'Все стратегии →' : 'All strategies →'} />
            <DeepLink href="/research" label={tr('deepResearch')} />
          </div>
        </>
      )}
    </Panel>
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
          <DeepLink href="/strategies" label={tr('fullTournament')} />
        </>
      )}
    </div>
  );
}

/* ───────────────────────────────────── AGGRESSIVE LAB SECTION ─────────────────────
   The 10-15% strategies the desk REFUSES, paper-tested in parallel and shown WITH the tail so the
   owner can SEE them (like the tournament) and CHOOSE later. Rendered like the tournament BUT the
   risk/tail columns (max-DD, tail-in-stress, risk-class) are PROMINENT, not optional — and a giant
   OUTSIDE-RiskPolicy banner makes clear these are NEVER live-allocated. Offline/unavailable show
   honest states, NEVER a blank or fabricated leaderboard. */
function AggressiveLabSection({ aggressive, contrast, lang, tr }) {
  const offline = aggressive === null;            // fetch failed → API offline
  const loading = aggressive === undefined;       // still polling
  const available = aggressive && aggressive.available === true;
  const unavailable = aggressive && aggressive.available === false;  // 200 but no scorecard yet
  const trustworthy = aggressive ? aggressive.trustworthy === true : false;
  const selectOn = aggressive ? aggressive.owner_select_enabled === true : false;
  const rows = (aggressive && Array.isArray(aggressive.strategies)) ? aggressive.strategies : [];

  const classTone = (c) => (c === 'A' ? 'ok' : c === 'B' ? 'teal' : c === 'D' ? 'warn' : 'warn');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* OUTSIDE-RiskPolicy banner — mandatory, unmissable. */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap', padding: '14px 18px', borderRadius: 'var(--r-md)', background: 'rgba(242,109,109,.10)', border: '1px solid rgba(242,109,109,.30)' }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--danger)', flexShrink: 0, marginTop: 6 }} aria-hidden="true" />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ ...mono, fontSize: '.7rem', fontWeight: 700, color: 'var(--danger)', letterSpacing: '.06em' }}>
            OUTSIDE RISKPOLICY · ADVISORY · PAPER-ONLY
          </span>
          <span style={{ fontSize: '.8125rem', color: 'rgba(242,109,109,.85)', lineHeight: 1.5, maxWidth: 820 }}>{tr('aggBanner')}</span>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <SectionHead eyebrow={tr('aggEyebrow')} title={tr('aggTitle')} intro={tr('aggIntro')} />
        <SourceTag live={!offline && !loading} lang={lang} />
      </div>

      {offline ? (
        <Panel><p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('aggOffline')}</p></Panel>
      ) : loading ? (
        <Panel><p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('connecting')}</p></Panel>
      ) : unavailable || rows.length === 0 ? (
        <Panel><p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('aggUnavailable')}</p></Panel>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <Chip tone={trustworthy ? 'ok' : 'warn'}>{trustworthy ? tr('aggTrust') : (lang === 'ru' ? 'тонкий трек — не доверенный' : 'thin track — not trustworthy yet')}</Chip>
            <Chip tone="muted">{selectOn ? tr('aggSelected') + ': on' : (lang === 'ru' ? 'выбор: выкл' : 'selection: off')}</Chip>
          </div>
          {!trustworthy && (
            <p style={{ fontSize: '.75rem', color: 'var(--warn)', lineHeight: 1.5 }}>{tr('aggNotTrust')}</p>
          )}

          {/* The scorecard — return AND risk AND tail, side by side. Tail/risk columns PROMINENT. */}
          <div style={{ ...card, overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '.8125rem' }}>
                <thead>
                  <tr style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-muted)', background: 'var(--bg-surface-2)' }}>
                    <th style={{ textAlign: 'left', padding: '10px 14px' }}>{tr('aggStrategy')}</th>
                    <th style={{ textAlign: 'right', padding: '10px 14px' }}>{tr('aggReturn')}</th>
                    <th style={{ textAlign: 'right', padding: '10px 14px' }}>{tr('aggSharpe')}</th>
                    <th style={{ textAlign: 'right', padding: '10px 14px', color: 'var(--danger)' }}>{tr('aggMaxDd')}</th>
                    <th style={{ textAlign: 'right', padding: '10px 14px', color: 'var(--danger)' }} title={tr('aggTailNote')}>{tr('aggTail')} ⓘ</th>
                    <th style={{ textAlign: 'left', padding: '10px 14px' }}>{tr('aggClass')}</th>
                    <th style={{ textAlign: 'left', padding: '10px 14px' }}>{tr('aggVerdict')}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const sh = r.sharpe;
                    const shTxt = (sh == null || Number.isNaN(Number(sh)) || Number(sh) > 10)
                      ? (lang === 'ru' ? 'n/a' : 'n/a') : Number(sh).toFixed(2);
                    return (
                      <tr key={r.id || i} style={{ borderTop: '1px solid var(--border)' }}>
                        <td style={{ ...mono, padding: '10px 14px', color: 'var(--text-primary)' }}>
                          {(r.name || r.id || '?')}
                          {r.mandate && <span style={{ display: 'block', fontSize: '.6875rem', color: 'var(--text-faint)' }}>{r.mandate}</span>}
                        </td>
                        <td style={{ ...mono, padding: '10px 14px', textAlign: 'right', color: 'var(--ok)', fontWeight: 600 }}>{fmtPct(r.net_return_pct, 1)}</td>
                        <td style={{ ...mono, padding: '10px 14px', textAlign: 'right', color: 'var(--text-muted)' }} title={shTxt === 'n/a' ? (lang === 'ru' ? 'недостаточно данных' : 'INSUFFICIENT_DATA') : ''}>{shTxt}</td>
                        <td style={{ ...mono, padding: '10px 14px', textAlign: 'right', color: 'var(--danger)', fontWeight: 600 }}>{fmtPct(r.max_drawdown_pct, 1)}</td>
                        <td style={{ ...mono, padding: '10px 14px', textAlign: 'right', color: 'var(--danger)', fontWeight: 700 }}>{fmtPct(r.tail_loss_in_stress_pct, 1)}</td>
                        <td style={{ padding: '10px 14px' }}>
                          <Chip tone={classTone(r.risk_class)} title={r.risk_class_label || ''}>{r.risk_class || '?'}{r.risk_shape ? ' · ' + r.risk_shape : ''}</Chip>
                        </td>
                        <td style={{ ...mono, padding: '10px 14px', color: 'var(--text-secondary)', fontSize: '.6875rem' }}>{r.verdict || '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
            {selectOn ? tr('aggSelectOn') : tr('aggSelectOff')}
          </p>
        </>
      )}

      {/* ── THE ANNUAL CONTRAST — the owner's sales surface (15% aggressive vs the steady ~5%) ── */}
      <AnnualContrastView contrast={contrast} lang={lang} tr={tr} />
    </div>
  );
}

/* ───────────────────────── ANNUAL CONTRAST (the owner's sales tool) ───────────────────
   Two equity curves over a year — the 10-15% aggressive book vs the desk's REAL steady ~5%
   book — with the aggressive book's drawdowns DATED + labelled by event. Two kinds of dip are
   visually DISTINCT and never blended: a REALIZED dip (real peak-to-trough in the backtest
   equity, solid danger marker) vs a MODELED stress marker (the tail a book of this shape would
   take through a dated 2024-26 event, hollow/dashed). Everything renders from the producer file
   served VERBATIM by /api/aggressive-lab/annual-contrast — NO fabricated curve, honest unavailable
   when the file is absent. Reusable: the shareable page imports this same component. */
export function AnnualContrastView({ contrast, lang, tr, embedded = false }) {
  const offline = contrast === null;
  const loading = contrast === undefined;
  const available = contrast && contrast.available === true;
  const strategies = (available && Array.isArray(contrast.strategies)) ? contrast.strategies : [];

  // Pick the most illustrative aggressive book by default: the one with the deepest modeled tail.
  const [pickId, setPickId] = useState(null);
  const tailDepth = (s) => {
    const ov = (s.dated_drawdown_timeline && s.dated_drawdown_timeline.dated_stress_overlay) || [];
    return ov.reduce((m, o) => Math.min(m, Number(o.depth_pct) || 0), 0);
  };
  const sorted = [...strategies].sort((a, b) => tailDepth(a) - tailDepth(b));
  const chosen = strategies.find((s) => s.strategy_id === pickId) || sorted[0] || null;

  if (offline || loading) {
    return (
      <div style={{ ...card, padding: 24 }}>
        <SectionHead eyebrow={tr('acEyebrow')} title={tr('acTitle')} />
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{offline ? tr('aggOffline') : tr('connecting')}</p>
      </div>
    );
  }
  if (!available || !chosen) {
    return (
      <div style={{ ...card, padding: 24 }}>
        <SectionHead eyebrow={tr('acEyebrow')} title={tr('acTitle')} />
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>
          {(contrast && contrast.unavailable_reason) || tr('aggUnavailable')}
        </p>
      </div>
    );
  }

  // The trailing-12m window is the headline; fall back to the first window present.
  const win = (chosen.windows || []).find((w) => w.window === 'trailing_12m') || (chosen.windows || [])[0];
  const stableApy = Number(contrast.stable_apy_pct);
  const notional = Number((win && win.notional_usd) || contrast.notional_usd || 100000);
  const overlay = (chosen.dated_drawdown_timeline && chosen.dated_drawdown_timeline.dated_stress_overlay) || [];
  const realized = (chosen.dated_drawdown_timeline && chosen.dated_drawdown_timeline.realized_drawdowns) || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: embedded ? 0 : 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <SectionHead eyebrow={tr('acEyebrow')} title={tr('acTitle')} intro={tr('acIntro')} />
        {!embedded && <SourceTag live lang={lang} />}
      </div>

      {/* book picker + proof + steady-baseline source (proves the ~5% is REAL, not a strawman) */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <label style={{ ...mono, fontSize: '.6875rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '.06em' }}>{tr('acPickStrat')}:</label>
        <select
          value={chosen.strategy_id}
          onChange={(e) => setPickId(e.target.value)}
          style={{ ...mono, fontSize: '.75rem', padding: '5px 10px', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-2)', color: 'var(--text-primary)', border: '1px solid var(--border-strong)' }}
        >
          {sorted.map((s) => (
            <option key={s.strategy_id} value={s.strategy_id}>
              {s.strategy_id} · {s.risk_class} · ~{fmtPct(s.headline_apy_pct, 0)}
            </option>
          ))}
        </select>
        {contrast.proof_hash && <Chip tone="muted">{tr('acProof')} {String(contrast.proof_hash).slice(0, 12)}…</Chip>}
        <Chip tone="muted">{tr('acStableSrc')}: {contrast.stable_apy_source || NA}</Chip>
      </div>

      {/* THE TWO CURVES + dated drawdown annotations */}
      <ContrastChart
        aggressive={win && win.aggressive}
        stableApyPct={stableApy}
        notional={notional}
        overlay={overlay}
        realized={realized}
        dateFrom={win && win.date_from}
        dateTo={win && win.date_to}
        lang={lang}
        tr={tr}
      />

      {/* CONTRAST TABLE — CAGR / max-DD / days-underwater / cost-of-chasing, side by side */}
      <div style={{ ...card, overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '.8125rem' }}>
            <thead>
              <tr style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-muted)', background: 'var(--bg-surface-2)' }}>
                <th style={{ textAlign: 'left', padding: '10px 14px' }}>{tr('acColSide')}</th>
                <th style={{ textAlign: 'right', padding: '10px 14px' }}>{tr('acColCagr')}</th>
                <th style={{ textAlign: 'right', padding: '10px 14px', color: 'var(--danger)' }}>{tr('acColMaxDd')}</th>
                <th style={{ textAlign: 'right', padding: '10px 14px' }}>{tr('acColUnderwater')}</th>
                <th style={{ textAlign: 'right', padding: '10px 14px' }}>{tr('acColCost')}</th>
              </tr>
            </thead>
            <tbody>
              <ContrastRow side={tr('acAggSide')} tone="var(--danger)" m={win && win.aggressive} cost={win && win.cost_of_chasing_dd_pct} />
              <ContrastRow side={tr('acStableSide')} tone="var(--ok)" m={win && win.stable} cost={0} />
            </tbody>
          </table>
        </div>
      </div>

      {/* THE DRAWDOWN TIMELINE, DATED — realized vs modeled, clearly labelled, real dates+events */}
      <div style={{ ...card, padding: 20 }}>
        <h3 style={{ ...HEADING, fontSize: '1.05rem', marginBottom: 12 }}>{tr('acDdHead')}</h3>
        {realized.length === 0 && (
          <p style={{ fontSize: '.75rem', color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 12 }}>{tr('acNoRealized')}</p>
        )}
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '.8125rem' }}>
            <thead>
              <tr style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-muted)' }}>
                <th style={{ textAlign: 'left', padding: '8px 12px' }}>{tr('acDdDate')}</th>
                <th style={{ textAlign: 'left', padding: '8px 12px' }}>{tr('acDdEvent')}</th>
                <th style={{ textAlign: 'right', padding: '8px 12px', color: 'var(--danger)' }}>{tr('acDdDepth')}</th>
                <th style={{ textAlign: 'left', padding: '8px 12px' }}>{tr('acDdKind')}</th>
              </tr>
            </thead>
            <tbody>
              {realized.map((d, i) => (
                <tr key={'r' + i} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ ...mono, padding: '8px 12px' }}>{d.trough_date || d.peak_date || NA}</td>
                  <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>{d.source || (lang === 'ru' ? 'realized просадка в equity' : 'realized dip in equity')}</td>
                  <td style={{ ...mono, padding: '8px 12px', textAlign: 'right', color: 'var(--danger)', fontWeight: 700 }}>{fmtPct(d.depth_pct, 1)}</td>
                  <td style={{ padding: '8px 12px' }}><Chip tone="danger">{tr('acRealized')}</Chip></td>
                </tr>
              ))}
              {overlay.map((o, i) => (
                <tr key={'m' + i} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ ...mono, padding: '8px 12px' }}>{o.event_date || NA}</td>
                  <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>{o.event || NA}</td>
                  <td style={{ ...mono, padding: '8px 12px', textAlign: 'right', color: 'var(--warn)', fontWeight: 700 }}>{fmtPct(o.depth_pct, 1)}</td>
                  <td style={{ padding: '8px 12px' }}><Chip tone="warn">{tr('acModeled')}</Chip></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.6, maxWidth: 820 }}>{tr('acBottom')}</p>
      {!embedded && <DeepLink href="/annual-contrast" label={tr('acShareLink')} inline />}
    </div>
  );
}

function ContrastRow({ side, tone, m, cost }) {
  const mm = m || {};
  return (
    <tr style={{ borderTop: '1px solid var(--border)' }}>
      <td style={{ ...mono, padding: '10px 14px', color: tone, fontWeight: 600 }}>
        <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: tone, marginRight: 8, verticalAlign: 'middle' }} aria-hidden="true" />
        {side}
      </td>
      <td style={{ ...mono, padding: '10px 14px', textAlign: 'right' }}>{fmtSigned(mm.cagr_pct, 1)}</td>
      <td style={{ ...mono, padding: '10px 14px', textAlign: 'right', color: 'var(--danger)', fontWeight: 600 }}>{fmtPct(mm.max_drawdown_pct, 1)}</td>
      <td style={{ ...mono, padding: '10px 14px', textAlign: 'right' }}>{mm.days_underwater == null ? NA : mm.days_underwater}</td>
      <td style={{ ...mono, padding: '10px 14px', textAlign: 'right', color: 'var(--warn)' }}>{cost == null ? NA : fmtPct(cost, 1)}</td>
    </tr>
  );
}

/* The two equity curves + dated drawdown markers, as inline SVG (stdlib-only spirit — no chart lib).
   The aggressive curve is its realized window path (start_equity → end_equity, compounded — an
   honest representation of the window's total return, NOT invented points). The steady line
   compounds the REAL stable rate. Dated markers sit at their real event_date on the time axis:
   a REALIZED dip = solid filled danger dot; a MODELED stress marker = hollow dashed warn ring —
   the two are visually distinct so a modeled overlay is NEVER passed off as a realized dip. */
function ContrastChart({ aggressive, stableApyPct, notional, overlay, realized, dateFrom, dateTo, lang, tr }) {
  const W = 720, H = 300, PADL = 64, PADR = 16, PADT = 24, PADB = 52;
  const plotW = W - PADL - PADR, plotH = H - PADT - PADB;

  const t0 = dateFrom ? new Date(dateFrom + 'T00:00:00Z').getTime() : null;
  const t1 = dateTo ? new Date(dateTo + 'T00:00:00Z').getTime() : null;
  const span = (t0 != null && t1 != null && t1 > t0) ? (t1 - t0) : null;
  const fx = (dateStr) => {
    if (span == null || !dateStr) return null;
    const t = new Date(dateStr + 'T00:00:00Z').getTime();
    const frac = Math.max(0, Math.min(1, (t - t0) / span));
    return PADL + frac * plotW;
  };

  const aggStart = Number((aggressive && aggressive.start_equity_usd) || notional);
  const aggEnd = Number((aggressive && aggressive.end_equity_usd) || aggStart);
  const stableEnd = notional * (1 + (Number(stableApyPct) || 0) / 100);

  // y-domain: from a little below notional to a little above the higher endpoint.
  const yMax = Math.max(aggStart, aggEnd, stableEnd, notional) * 1.04;
  const yMin = Math.min(aggStart, aggEnd, stableEnd, notional) * 0.97;
  const fy = (usd) => {
    const frac = (Number(usd) - yMin) / (yMax - yMin || 1);
    return PADT + (1 - Math.max(0, Math.min(1, frac))) * plotH;
  };

  // N-step compounded path between endpoints (geometric — honest interpolation of the window CAGR).
  const STEPS = 48;
  const path = (start, end) => {
    const g = end / (start || 1);
    const pts = [];
    for (let i = 0; i <= STEPS; i++) {
      const f = i / STEPS;
      const x = PADL + f * plotW;
      const y = fy(start * Math.pow(g, f));
      pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
    }
    return pts.join(' ');
  };

  const yTicks = 4;
  const ticks = Array.from({ length: yTicks + 1 }, (_, i) => yMin + (i / yTicks) * (yMax - yMin));

  return (
    <div style={{ ...card, padding: 16 }}>
      {/* legend */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 8, fontSize: '.6875rem', color: 'var(--text-muted)' }}>
        <span><span style={{ display: 'inline-block', width: 14, height: 3, background: 'var(--danger)', marginRight: 6, verticalAlign: 'middle' }} />{tr('acAggLegend')}</span>
        <span><span style={{ display: 'inline-block', width: 14, height: 3, background: 'var(--ok)', marginRight: 6, verticalAlign: 'middle' }} />{tr('acStableLegend')}</span>
        <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: '50%', background: 'var(--danger)', marginRight: 6, verticalAlign: 'middle' }} />{tr('acRealizedLegend')}</span>
        <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: '50%', background: 'transparent', border: '2px dashed var(--warn)', marginRight: 6, verticalAlign: 'middle' }} />{tr('acModeledLegend')}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="aggressive vs steady equity curves with dated drawdowns" style={{ display: 'block' }}>
        {/* y grid + labels */}
        {ticks.map((v, i) => {
          const y = fy(v);
          return (
            <g key={'y' + i}>
              <line x1={PADL} y1={y} x2={W - PADR} y2={y} stroke="var(--border)" strokeWidth="1" />
              <text x={PADL - 8} y={y + 3} textAnchor="end" fontSize="9" fill="var(--text-faint)" fontFamily="var(--font-mono)">{usdCompact(v)}</text>
            </g>
          );
        })}
        {/* x axis date labels */}
        <text x={PADL} y={H - PADB + 18} textAnchor="start" fontSize="9" fill="var(--text-faint)" fontFamily="var(--font-mono)">{dateFrom || ''}</text>
        <text x={W - PADR} y={H - PADB + 18} textAnchor="end" fontSize="9" fill="var(--text-faint)" fontFamily="var(--font-mono)">{dateTo || ''}</text>

        {/* the two curves */}
        <polyline points={path(notional, stableEnd)} fill="none" stroke="var(--ok)" strokeWidth="2.5" strokeLinejoin="round" />
        <polyline points={path(aggStart, aggEnd)} fill="none" stroke="var(--danger)" strokeWidth="2.5" strokeLinejoin="round" />

        {/* REALIZED drawdown markers — solid filled danger dots (real dips in the equity) */}
        {realized.map((d, i) => {
          const x = fx(d.trough_date || d.peak_date);
          if (x == null) return null;
          const y = fy(d.book_equity_at_event_usd != null ? d.book_equity_at_event_usd : aggStart);
          return (
            <g key={'rm' + i}>
              <circle cx={x} cy={y} r="5" fill="var(--danger)" stroke="var(--bg-surface)" strokeWidth="1.5" />
              <line x1={x} y1={PADT} x2={x} y2={H - PADB} stroke="var(--danger)" strokeWidth="1" strokeDasharray="2 3" opacity="0.35" />
            </g>
          );
        })}

        {/* MODELED stress markers — hollow dashed warn rings (the tail by shape, NOT a realized dip) */}
        {overlay.map((o, i) => {
          const x = fx(o.event_date);
          if (x == null) return null;
          const y = fy(o.book_equity_at_event_usd != null ? o.book_equity_at_event_usd : aggEnd);
          const label = `${fmtPct(o.depth_pct, 0)} · ${o.event_date || ''}`;
          const anchor = x > W * 0.66 ? 'end' : 'start';
          const dx = anchor === 'end' ? -8 : 8;
          return (
            <g key={'om' + i}>
              <line x1={x} y1={PADT} x2={x} y2={H - PADB} stroke="var(--warn)" strokeWidth="1" strokeDasharray="3 3" opacity="0.45" />
              <circle cx={x} cy={y} r="5" fill="transparent" stroke="var(--warn)" strokeWidth="2" strokeDasharray="3 2" />
              <text x={x + dx} y={Math.max(PADT + 10, y - 8)} textAnchor={anchor} fontSize="9.5" fill="var(--warn)" fontFamily="var(--font-mono)" fontWeight="700">{label}</text>
            </g>
          );
        })}
      </svg>
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

      {/* Per-underlying refusal verdicts + the public refusal log now live in the dedicated
          "Refusals & proof" tab (the trust surface) — kept out of here to avoid duplication.
          A pointer keeps them discoverable from the desks. */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Chip tone="ok">SAFE {refCounts.SAFE ?? 0}</Chip>
        <Chip tone="warn">WATCH {refCounts.WATCH ?? 0}</Chip>
        <Chip tone="danger">REFUSE {refCounts.REFUSE ?? 0}</Chip>
        <span style={{ fontSize: '.75rem', color: 'var(--text-muted)' }}>
          {lang === 'ru' ? '→ полные вердикты отказа и tamper-evident лог в разделе «Отказы и доказательства»' : '→ full refusal verdicts + the tamper-evident log are in the "Refusals & proof" tab'}
        </span>
      </div>

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
        <DeepLink href="/proof-of-reserves" label={tr('deepPor')} />
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
            {safe && safe.stale && <Chip tone="warn">stale</Chip>}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <SafetyRung active={false} label={tr('ladderDl')} color="var(--text-faint)" />
            <SafetyRung active={safeState === 'SOFT_DERISK'} label={tr('ladderSoft')} color="var(--warn)" />
            <SafetyRung active={safeState === 'HARD_KILL'} label={tr('ladderHard')} color="var(--danger)" />
          </div>
          <p style={{ ...SUBTEXT, marginTop: 14 }}>
            {lang === 'ru' ? 'Детерминированная RiskPolicy v1.0 — без LLM. approved=False не переопределить. Полная лестница с маркером живой просадки + scorecard cutover — во вкладке «Риск».' : 'Deterministic RiskPolicy v1.0 — LLM-free. approved=False can be overridden by no one. The full ladder with the live-drawdown marker + the cutover scorecard live in the "Risk" tab.'}
          </p>
        </Panel>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
        <DeepLink href="/system" label={tr('deepSystem')} />
        <DeepLink href="/status" label={tr('deepStatus')} />
        <DeepLink href="/verify" label={tr('proofVerifyCta')} />
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
      t: { en: 'Refusals & proof = the trust surface', ru: 'Отказы и доказательства = поверхность доверия' },
      b: {
        en: 'We publish what we refuse, not only what we trade. Every decision is in a tamper-evident hash chain you can re-derive yourself in <5 min (see /verify). The integrity badge flips red the instant a past byte is altered — that honesty IS the trust signal. The red-team verdict is our own adversarial harness trying to break us.',
        ru: 'Мы публикуем отказы, а не только сделки. Каждое решение — в защищённой от подмены хеш-цепочке, которую вы можете пересчитать сами за <5 мин (см. /verify). Бейдж целостности краснеет в момент изменения прошлого байта — эта честность И ЕСТЬ сигнал доверия. Red-team вердикт — наш собственный adversarial harness, пытающийся нас сломать.',
      },
    },
    {
      t: { en: 'Risk = the kill-switch ladder', ru: 'Риск = лестница kill-switch' },
      b: {
        en: 'The deterministic two-tier safety ladder: DL-01 daily-loss 2% and DL-02 peak-drawdown 10% HALT allocation; SOFT de-risk at 5% halts new allocations; HARD kill at 10% moves all to cash. The marker is the live drawdown. The cutover scorecard shows honest CODE-readiness — which is NOT go-live: custody, real capital, audit and the 30-day track are owner-only blockers.',
        ru: 'Детерминированная двухуровневая лестница защиты: DL-01 дневной убыток 2% и DL-02 peak-просадка 10% HALT аллокации; SOFT de-risk при 5% стоп новых аллокаций; HARD kill при 10% всё в кэш. Маркер — живая просадка. Scorecard cutover показывает честную CODE-готовность — что НЕ есть go-live: custody, реальный капитал, аудит и 30-дневный трек — owner-only блокеры.',
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

          <div style={{ marginTop: 14, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <DeepLink href="/exit-nav" label={tr('deepExitNav')} inline />
            <DeepLink href="/rates-desk" label={tr('exitMethodology')} inline />
          </div>
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
            <DeepLink href="/refusals" label={tr('deepRefusals')} />
            <DeepLink href="/rates-desk" label={tr('deepRates')} />
            <DeepLink href="/research" label={tr('deepResearch')} />
          </div>
        </>
      )}
    </Panel>
  );
}

/* ═══════════════════════════════════ DAY-30 READINESS (overview) ═════════════════════════════════
 * The deterministic /api/v1/day30 artifact: evidenced days, realized return/drawdown, honest verdict.
 * Risk-adjusted metrics (Sharpe) read THIN until ~20 returns exist — shown honestly, never faked.
 * ─────────────────────────────────────────────────────────────────────────────────────────────── */
function Day30Panel({ day30, lang, tr }) {
  const offline = day30 === null;
  const loading = day30 === undefined;
  const live = !offline && !loading;
  const ev = (day30 && day30.evidenced) || {};
  const rm = ev.risk_metrics || {};
  const verdict = day30 && day30.verdict;
  const verdictTone = verdict === 'READY' ? 'ok' : verdict === 'NOT_READY' ? 'warn' : 'muted';

  return (
    <Panel>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <div>
          <Eyebrow>{tr('day30Title')}</Eyebrow>
          <p style={{ ...SUBTEXT, marginTop: 0, maxWidth: 720 }}>{tr('day30Sub')}</p>
        </div>
        <SourceTag live={live} lang={lang} />
      </div>
      {offline ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('day30Offline')}</p>
      ) : loading ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('connecting')}</p>
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
            <span style={{ fontSize: '.8125rem', color: 'var(--text-secondary)' }}>{tr('day30Verdict')}:</span>
            <Chip tone={verdictTone}>{verdict || NA}</Chip>
            {day30.verdict_reason && <span style={{ fontSize: '.75rem', color: 'var(--text-muted)' }}>{day30.verdict_reason}</span>}
          </div>
          <div style={{ marginBottom: 14 }}>
            <Bar value={day30.readiness_pct || 0} max={100} color="var(--data-teal)" />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 12 }}>
            <Metric label={tr('day30Ready')} value={day30.readiness_pct == null ? NA : day30.readiness_pct.toFixed(1) + '%'} accent="var(--data-teal)" />
            <Metric label={lang === 'ru' ? 'Дней (evidenced)' : 'Days (evidenced)'} value={ev.evidenced_days == null ? NA : `${ev.evidenced_days} / ${ev.min_track_days ?? DAYS_NEEDED}`} />
            <Metric label={tr('day30Realized')} value={fmtSigned(ev.realized_total_return_pct, 3)} accent={(ev.realized_total_return_pct ?? 0) >= 0 ? 'var(--ok)' : 'var(--danger)'} />
            <Metric label={tr('day30Dd')} value={fmtPct(ev.realized_max_drawdown_pct, 2)} />
            <Metric
              label={tr('day30Sharpe')}
              value={rm.sharpe == null ? tr('unknown') : Number(rm.sharpe).toFixed(2)}
              accent={rm.sharpe == null ? 'var(--text-muted)' : undefined}
              sub={rm.status === 'THIN' ? (lang === 'ru' ? `THIN · ${rm.n_returns ?? 0}/${rm.min_returns ?? 20} доходностей` : `THIN · ${rm.n_returns ?? 0}/${rm.min_returns ?? 20} returns`) : undefined}
            />
          </div>
        </>
      )}
    </Panel>
  );
}

/* ═══════════════════════════════════ RISK SECTION (WS-7.2 / 7.3) ═════════════════════════════════
 * Three panels: the two-tier kill-switch ladder (live drawdown marker), the cutover readiness
 * scorecard (honest CODE-readiness ≠ go-live), and the red-team verdict. Each polls its own API.
 * ─────────────────────────────────────────────────────────────────────────────────────────────── */
function RiskSection({ governance, safety, safeState, safeTone, execRead, redteam, lang, tr }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <SectionHead eyebrow={tr('riskEyebrow')} title={tr('riskTitle')} intro={tr('riskIntro')} />
      <KillSwitchLadder governance={governance} safety={safety} safeState={safeState} safeTone={safeTone} lang={lang} tr={tr} />
      <ExecutionReadinessPanel execRead={execRead} lang={lang} tr={tr} />
      <RedTeamPanel redteam={redteam} lang={lang} tr={tr} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
        <DeepLink href="/system" label={tr('deepSystem')} />
        <DeepLink href="/verify" label={tr('proofVerifyCta')} />
      </div>
    </div>
  );
}

/* ── kill-switch two-tier ladder viz (DL-01 2% / SOFT 5% / HARD 10% / DL-02 10%) ──
 * Canonical thresholds are RiskPolicy literals (daily_limits.py MAX_DAILY_LOSS_PCT=2, MAX_DRAWDOWN_PCT=10;
 * derisk SOFT=5, HARD kill=10). The live drawdown comes from /api/live/safety; if absent we hide the
 * marker rather than fabricate a position. The active rung is driven by the live safety STATE. */
function KillSwitchLadder({ governance, safety, safeState, safeTone, lang, tr }) {
  const govOffline = governance === null;
  const safetyOffline = safety == null; // null=offline OR undefined=loading → no marker
  // Live drawdown is parsed from the safety reason string ("drawdown 0.00% < 5.0%") when present.
  let liveDdPct = null;
  if (safety && typeof safety.drawdown_pct === 'number') liveDdPct = safety.drawdown_pct;
  else if (safety && typeof safety.reason === 'string') {
    const m = safety.reason.match(/drawdown\s+([\d.]+)\s*%/i);
    if (m) liveDdPct = parseFloat(m[1]);
  }
  const posture = governance && governance.dual_control_posture;
  const enforced = posture && posture.enforced === true;

  // Ladder rungs, ascending drawdown. SCALE is 0..10% for the marker position.
  const SCALE_MAX = 10;
  const rungs = [
    { key: 'dl1', pct: 2, label: tr('ladderRungDl1'), action: tr('ladderDl1Action'), color: 'var(--warn)', active: false },
    { key: 'soft', pct: 5, label: tr('ladderRungSoft'), action: tr('ladderSoftAction'), color: 'var(--warn)', active: safeState === 'SOFT_DERISK' },
    { key: 'hard', pct: 10, label: tr('ladderRungHard'), action: tr('ladderHardAction'), color: 'var(--danger)', active: safeState === 'HARD_KILL' },
    { key: 'dl2', pct: 10, label: tr('ladderRungDl2'), action: tr('ladderDl2Action'), color: 'var(--danger)', active: safeState === 'HARD_KILL' },
  ];
  const markerFrac = liveDdPct == null ? null : Math.max(0, Math.min(1, liveDdPct / SCALE_MAX));

  return (
    <Panel>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <h3 style={{ ...HEADING, fontSize: '1.15rem' }}>{tr('ladderVizTitle')}</h3>
        <SourceTag live={!safetyOffline} lang={lang} />
      </div>
      <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: 16, maxWidth: 720 }}>{tr('ladderVizSub')}</p>

      {/* current state row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        <span style={{ fontSize: '.8125rem', color: 'var(--text-secondary)' }}>{tr('ladderState')}:</span>
        {safety ? <Chip tone={safeTone}>{safeState}</Chip> : <Chip tone="muted">{NA}</Chip>}
        {safety && safety.stale && <Chip tone="warn">stale</Chip>}
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)' }}>{tr('ladderCurrentDd')}</span>
          <span style={{ ...mono, fontSize: '.95rem', fontWeight: 700, color: liveDdPct == null ? 'var(--text-muted)' : liveDdPct >= 5 ? 'var(--danger)' : 'var(--data-teal)' }}>
            {liveDdPct == null ? NA : liveDdPct.toFixed(2) + '%'}
          </span>
        </span>
      </div>

      {/* horizontal scale with marker */}
      <div style={{ position: 'relative', height: 40, marginBottom: 8 }}>
        {/* gradient track: clear → soft (amber) → hard (red) */}
        <div style={{ position: 'absolute', top: 16, left: 0, right: 0, height: 8, borderRadius: 'var(--r-full)', background: 'linear-gradient(90deg, rgba(52,211,153,.35) 0%, rgba(242,181,60,.4) 50%, rgba(242,109,109,.55) 100%)' }} />
        {/* rung ticks */}
        {rungs.filter((r) => r.key !== 'dl2').map((r) => (
          <div key={r.key} style={{ position: 'absolute', top: 8, left: `${(r.pct / SCALE_MAX) * 100}%`, transform: 'translateX(-50%)', textAlign: 'center' }}>
            <div style={{ width: 2, height: 24, background: r.active ? r.color : 'var(--border-strong)', margin: '0 auto' }} />
          </div>
        ))}
        {/* live drawdown marker */}
        {markerFrac != null && (
          <div title={tr('ladderCurrentDd') + ': ' + (liveDdPct != null ? liveDdPct.toFixed(2) + '%' : NA)}
            style={{ position: 'absolute', top: 4, left: `${markerFrac * 100}%`, transform: 'translateX(-50%)', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <span style={{ ...mono, fontSize: '.625rem', color: 'var(--text-primary)', fontWeight: 700, whiteSpace: 'nowrap' }}>▼</span>
            <div style={{ width: 3, height: 18, background: 'var(--text-primary)', borderRadius: 2 }} />
          </div>
        )}
      </div>
      {/* x-axis labels */}
      <div style={{ position: 'relative', height: 14, marginBottom: 16 }}>
        {[0, 2, 5, 10].map((p) => (
          <span key={p} style={{ ...mono, position: 'absolute', left: `${(p / SCALE_MAX) * 100}%`, transform: 'translateX(-50%)', fontSize: '.5625rem', color: 'var(--text-faint)' }}>{p}%</span>
        ))}
      </div>

      {/* rung detail rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rungs.map((r) => (
          <div key={r.key} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 'var(--r-sm)', background: r.active ? 'rgba(242,109,109,.06)' : 'var(--bg-base)', border: `1px solid ${r.active ? r.color : 'var(--border)'}` }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: r.active ? r.color : 'var(--text-faint)', flexShrink: 0, animation: r.active ? 'pulse 3s ease-in-out infinite' : 'none' }} aria-hidden="true" />
            <span style={{ ...mono, fontSize: '.75rem', fontWeight: 600, color: r.active ? 'var(--text-primary)' : 'var(--text-secondary)', width: 132, flexShrink: 0 }}>{r.label}</span>
            <span style={{ ...mono, fontSize: '.75rem', color: r.color, width: 44, flexShrink: 0 }}>{r.pct}%</span>
            <span style={{ fontSize: '.75rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>{r.action}</span>
          </div>
        ))}
      </div>

      {/* governance dual-control posture */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 14 }}>
        <span style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)' }}>{tr('govPosture')}:</span>
        {govOffline
          ? <Chip tone="muted">{NA}</Chip>
          : <Chip tone={enforced ? 'ok' : 'muted'}>{enforced ? tr('govEnforced') : tr('govAdvisory')}</Chip>}
      </div>

      {govOffline && <p style={{ fontSize: '.6875rem', color: 'var(--text-faint)', lineHeight: 1.5, marginTop: 10 }}>{tr('ladderGovOffline')}</p>}
      {safetyOffline && <p style={{ fontSize: '.6875rem', color: 'var(--text-faint)', lineHeight: 1.5, marginTop: 6 }}>{tr('ladderSafetyOffline')}</p>}
    </Panel>
  );
}

/* ── cutover readiness scorecard (honest CODE-readiness ≠ go-live) ── */
function ExecutionReadinessPanel({ execRead, lang, tr }) {
  const offline = execRead === null;
  const loading = execRead === undefined;
  const live = !offline && !loading;
  const checks = (execRead && execRead.checks) || {};
  const checkEntries = Object.entries(checks);
  // CODE-readiness = non-blocker checks passing / non-blocker checks total (the part code controls).
  const codeChecks = checkEntries.filter(([, c]) => c && c.blocker !== true);
  const codePass = codeChecks.filter(([, c]) => c && c.ok === true).length;
  const codeReadyPct = execRead && execRead.code_readiness_pct != null
    ? execRead.code_readiness_pct
    : (codeChecks.length ? (codePass / codeChecks.length) * 100 : null);
  const blockers = (execRead && (execRead.owner_only_blockers || execRead.live_blockers)) || [];
  const readyForLive = execRead && execRead.ready_for_live === true;

  return (
    <Panel>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <h3 style={{ ...HEADING, fontSize: '1.15rem' }}>{tr('execTitle')}</h3>
          <Chip tone="warn">{tr('execNotGoLive')}</Chip>
        </div>
        <SourceTag live={live} lang={lang} />
      </div>
      <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: 14, maxWidth: 720 }}>{tr('execWhat')}</p>

      {offline ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('execOffline')}</p>
      ) : loading ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('connecting')}</p>
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
            <Metric label={tr('execCodeReady')} value={codeReadyPct == null ? NA : codeReadyPct.toFixed(0) + '%'} accent="var(--data-teal)" />
            <Metric label={tr('execPosture')} value={execRead.posture || NA} />
            <Metric label={tr('execReadyForLive')} value={readyForLive ? (lang === 'ru' ? 'ДА' : 'YES') : (lang === 'ru' ? 'НЕТ' : 'NO')} accent={readyForLive ? 'var(--ok)' : 'var(--warn)'} sub={lang === 'ru' ? 'owner-gated' : 'owner-gated'} />
          </div>

          {/* code defenses */}
          {checkEntries.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', marginBottom: 8 }}>{tr('execChecks')}</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {checkEntries.map(([name, c]) => {
                  const tone = c.ok === true ? 'ok' : c.blocker ? 'danger' : 'warn';
                  const lbl = c.ok === true ? tr('pass') : c.blocker ? tr('fail') : tr('pending');
                  return (
                    <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '.8125rem' }}>
                      <span style={{ width: 78, flexShrink: 0 }}><Chip tone={tone}>{lbl}</Chip></span>
                      <span style={{ ...mono, color: 'var(--text-primary)', width: 200, flexShrink: 0, fontSize: '.75rem' }}>{name.replace(/_/g, ' ')}</span>
                      {c.blocker && <Chip tone="muted">owner</Chip>}
                      {c.detail && <span style={{ color: 'var(--text-muted)', fontSize: '.6875rem' }}>{c.detail}</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* owner-only blockers */}
          {blockers.length > 0 && (
            <div style={{ ...card, padding: '14px 16px', background: 'var(--bg-base)', borderLeft: '3px solid var(--warn)', marginTop: 16 }}>
              <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--warn)', marginBottom: 8 }}>{tr('execOwnerBlockers')}</p>
              <ul style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {blockers.map((b, i) => (
                  <li key={i} style={{ fontSize: '.75rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>{b}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

/* ── red-team verdict ("we red-team ourselves") ── */
function RedTeamPanel({ redteam, lang, tr }) {
  const offline = redteam === null;
  const loading = redteam === undefined;
  const unavailable = redteam && redteam.available === false;
  const live = !offline && !loading && !unavailable;
  const ok = redteam && redteam.ok === true;
  const verdictTone = ok ? 'ok' : redteam && redteam.ok === false ? 'danger' : 'muted';

  return (
    <Panel>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <h3 style={{ ...HEADING, fontSize: '1.15rem' }}>{tr('redTitle')}</h3>
        <SourceTag live={live} lang={lang} />
      </div>
      <p style={{ fontSize: '.8125rem', color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: 14, maxWidth: 720 }}>{tr('redWhat')}</p>

      {offline ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('redOffline')}</p>
      ) : loading ? (
        <p style={{ fontSize: '.875rem', color: 'var(--text-muted)' }}>{tr('connecting')}</p>
      ) : unavailable ? (
        <p style={{ fontSize: '.875rem', color: 'var(--warn)' }}>{tr('redNone')}</p>
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
            <span style={{ fontSize: '.8125rem', color: 'var(--text-secondary)' }}>{tr('redVerdict')}:</span>
            <Chip tone={verdictTone}>{ok ? tr('redPass') : redteam.ok === false ? tr('redFail') : NA}</Chip>
            {redteam.surface && <Chip tone="muted">{redteam.surface}</Chip>}
            {redteam.live_data_untouched === true && <Chip tone="ok">{tr('redLiveUntouched')} ✓</Chip>}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 10 }}>
            <Metric label={tr('redScenarios')} value={redteam.n == null ? NA : redteam.n} />
            <Metric label={tr('redCaught')} value={redteam.n_caught == null ? NA : redteam.n_caught} accent="var(--ok)" />
            <Metric label={tr('redEscaped')} value={redteam.n_failed == null ? NA : redteam.n_failed} accent={redteam.n_failed ? 'var(--danger)' : undefined} />
          </div>
          {redteam.report_hash && (
            <div style={{ ...card, padding: '12px 14px', background: 'var(--bg-base)', marginTop: 14 }}>
              <p style={{ ...mono, fontSize: '.625rem', textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-faint)', marginBottom: 4 }}>{tr('redReportHash')}</p>
              <p style={{ ...mono, fontSize: '.6875rem', color: 'var(--data-teal)', wordBreak: 'break-all' }}>{redteam.report_hash}</p>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

/* ═══════════════════════════════════ PROOF SECTION (WS-7.1 trust surface) ═════════════════════════
 * The credibility surface: the public refusal log (tamper-evident chain), the rates proof summary,
 * per-underlying refusal verdicts, the fail-closed promotion refusals, and the red-team verdict.
 * Each child polls its own API; offline degrades that one panel only. Anchored by the /verify CTA.
 * ─────────────────────────────────────────────────────────────────────────────────────────────── */
function ProofSection({ decisions, track, refusal, refusalLog, promotion, redteam, lang, tr }) {
  const decCounts = (decisions && decisions.counts) || {};
  const trackDays = track && track.days != null ? track.days : null;
  const ratesLive = decisions != null;
  const refusalLive = refusal != null;
  const refUnderlyings = (refusal && Array.isArray(refusal.underlyings)) ? refusal.underlyings : [];
  const refCounts = (refusal && refusal.verdict_counts) || {};

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <SectionHead eyebrow={tr('proofEyebrow')} title={tr('proofTitle')} intro={tr('proofIntro')} />

      {/* prominent verify CTA — the "<5 min reproduce" front door */}
      <a href="/verify" style={{ ...card, padding: '16px 18px', background: 'var(--accent-bg)', border: '1px solid var(--accent-dim)', color: 'var(--accent-hover)', fontSize: '.875rem', fontWeight: 600, display: 'block' }}>
        {tr('proofVerifyCta')}
      </a>

      {/* the tamper-evident public refusal log (flagship) */}
      <RefusalLogPanel refusalLog={refusalLog} lang={lang} tr={tr} />

      {/* rates-desk proof summary */}
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
          <Metric label={tr('ratesEntries')} value={decCounts.ENTRY == null ? NA : decCounts.ENTRY} accent="var(--ok)" />
          <Metric label={tr('ratesRefusals')} value={decCounts.REFUSAL == null ? NA : decCounts.REFUSAL} accent={decCounts.REFUSAL ? 'var(--danger)' : undefined} />
          <Metric label={tr('ratesTrackDays')} value={trackDays == null ? NA : `${trackDays}d`} />
        </div>
        <div style={{ marginTop: 14 }}><DeepLink href="/rates-desk" label={tr('deepRates')} inline /></div>
      </Panel>

      {/* per-underlying refusal verdicts */}
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

      {/* fail-closed promotion refusals + tournament trust gate */}
      <PromotionRefusalPanel promotion={promotion} lang={lang} tr={tr} />

      {/* our own red-team verdict — published in the trust surface too */}
      <RedTeamPanel redteam={redteam} lang={lang} tr={tr} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
        <DeepLink href="/verify" label={tr('proofVerifyCta')} />
        <DeepLink href="/refusals" label={tr('deepRefusals')} />
        <DeepLink href="/proof-of-reserves" label={tr('deepPor')} />
      </div>
    </div>
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
