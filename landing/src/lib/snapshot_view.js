// snapshot_view.js — снимок В ФОРМЕ, к которой привыкли страницы, но НЕ из снимка.
//
// Зачем это есть (ADR-373, установка владельца ADR-357 п. 5). Тринадцать страниц читали
// `track_snapshot.json` напрямую и потому обновлялись ЕЖЕДНЕВНО, хотя владелец просил
// раз в неделю. Перевести их по одной значило бы тринадцать раз переписать обращения к
// полям; перевести переходником — тринадцать раз поменять ОДНУ строку импорта:
//
//     - import snap from '../data/track_snapshot.json';
//     + import snap from '../lib/snapshot_view.js';
//
// Правило соответствия живёт ЗДЕСЬ, в одном месте. Тринадцать копий этого правила по
// страницам были бы ровно тем классом «одно правило в нескольких копиях», который в этом
// проекте уже стоил и денег, и трёх месяцев вранья (см. `.claude/rules/adapters.md`).
//
// ⚠️ ЭТО ПЕРЕХОДНАЯ ФОРМА, а не рекомендуемая. Витрина (`site_numbers.js`) отдаёт число
// вместе с его родом, источником, единицей и причиной отсутствия; здесь всё это теряется
// ради того, чтобы старые страницы поехали без переписывания. НОВОЕ число брать
// `site_numbers.js`, а не отсюда.
//
// ⚠️ ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО. Ряд графика (`bars`, 114 точек, 64 КБ) на витрину не
// положен: он в восемь раз больше самой витрины, и копировать его туда значило бы завести
// второе место для тех же данных. Он остаётся ДНЕВНЫМ, и это названо вслух: у страницы,
// которая рисует график и рядом печатает ставку, ставка несёт СВОЮ дату замера
// (`realized_rate.js`), так что читатель видит, что число недельное, а кривая — по
// сегодня. Молчаливого смешения тактов нет.

import NUMBERS from '../data/site_numbers.json';
import RAW from '../data/track_snapshot.json';

const v = (fig) => (fig && typeof fig.value === 'number' && Number.isFinite(fig.value))
  ? fig.value
  : null;

const H = NUMBERS.headline || {};
const T = NUMBERS.track || {};
const P = NUMBERS.packages || {};

/** Снимок в прежней форме — значения из ВИТРИНЫ (недельный такт). */
export default {
  // ── даты ───────────────────────────────────────────────────────────────────
  // `as_of` = день ЗАМЕРА (не публикации): страницы печатают его как «данные на».
  as_of: NUMBERS.measured_at || null,
  generated_at: T.snapshot_generated_at || null,
  published_at: NUMBERS.published_at || null,

  // ── головные величины ──────────────────────────────────────────────────────
  paper_apy_pct: v(H.apy),
  max_drawdown_pct: v(H.drawdown),
  nav_usd: v(H.nav),
  end_equity: v(T.end_equity),
  real_track_days: v(H.evidenced_days),
  evidenced_anchor: H.evidenced_anchor || null,
  days_needed: v(T.days_needed),
  degraded: !!T.degraded,
  go_live_target: T.go_live_target ?? null,

  // ── гейт готовности ────────────────────────────────────────────────────────
  gates_passed: (H.gates && typeof H.gates.passed === 'number') ? H.gates.passed : null,
  gates_total: (H.gates && typeof H.gates.total === 'number') ? H.gates.total : null,
  go_live_state: (H.gates && H.gates.state) || null,

  // ── пакеты и книги ─────────────────────────────────────────────────────────
  packages: Object.fromEntries(Object.entries(P).map(
    ([k, p]) => [k, { apy_pct: v(p.apy), dd_pct: v(p.drawdown) }])),
  paper_tracks: Object.fromEntries(Object.entries(NUMBERS.books || {}).map(
    ([k, b]) => [k, {
      status: b.status || null,
      days_with_positions: (typeof b.days === 'number') ? b.days : null,
      positions_count: (typeof b.positions === 'number') ? b.positions : null,
      apy_pct: v(b.apy),
      dd_pct: v(b.drawdown),
      nav_usd: v(b.nav),
      evidence: 'paper',
      evidence_split: b.evidence_split || null,
    }])),

  // ── ряд графика: ДНЕВНОЙ, см. оговорку в шапке ─────────────────────────────
  bars: RAW.bars || [],
};
