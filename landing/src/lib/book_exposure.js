// book_exposure.js — the ONE way a page names what the paper book holds (P1 Wave 2, 2026-10-08).
//
// Before: five pages carried hand-typed protocol lists (Spark listed though not held, «T1 only»,
// a playground preset with Spark and Morpho as T1) while the book held compound_v3 / fluid_fusdc /
// maple / morpho_blue_base / aave_v3 with T2 at 50 %. Every such sentence now reads the shelf's
// `exposure` block (← track_snapshot.book_exposure ← data/current_positions.json + ADAPTER_REGISTRY
// tiers). Not measured ⇒ null, and the page says «not measured» — never a remembered list.
//
// No number of its own: shares come from the shelf, formatted by the one formatter (ADR-660).

import NUMBERS from './site_numbers.js';
import { fmtPct2 } from './pct_format.js';

const NAME = {
  aave_v3: 'Aave v3', compound_v3: 'Compound v3', fluid_fusdc: 'Fluid (fUSDC)', maple: 'Maple',
  morpho_blue_base: 'Morpho Blue (Base)', morpho_steakhouse: 'Morpho (Steakhouse vault)',
  sky_susds: 'Sky sUSDS', spark: 'Spark', susde: 'Ethena sUSDe',
};

/** Measured exposure rows, or null when the shelf does not carry a measured block. */
export function exposure(numbers = NUMBERS) {
  const ex = numbers && numbers.exposure;
  if (!ex || ex.state !== 'MEASURED' || !Array.isArray(ex.rows) || ex.rows.length === 0) return null;
  const rows = ex.rows
    .filter((r) => r && r.share && typeof r.share.value === 'number')
    .map((r) => ({ protocol: r.protocol, name: NAME[r.protocol] || r.protocol, tier: r.tier, share: r.share.value }));
  if (rows.length === 0) return null;
  const cash = ex.cash_share && typeof ex.cash_share.value === 'number' ? ex.cash_share.value : null;
  const tierShare = (t) => rows.filter((r) => r.tier === t).reduce((a, r) => a + r.share, 0);
  return { as_of: ex.as_of || null, rows, cash, t1: tierShare('T1'), t2: tierShare('T2') };
}

/** «Compound v3 (T1, 40.00%), Fluid (fUSDC) (T2, 20.00%), …» or null (not measured). */
export function protocolList(ru = false, numbers = NUMBERS) {
  const e = exposure(numbers);
  if (!e) return null;
  return e.rows.map((r) => `${r.name} (${r.tier}, ${fmtPct2(r.share, ru)})`).join(', ');
}

/** «T1 45.00% · T2 50.00% · cash 5.00%» or null (not measured). */
export function tierSummary(ru = false, numbers = NUMBERS) {
  const e = exposure(numbers);
  if (!e) return null;
  const parts = [`T1 ${fmtPct2(e.t1, ru)}`, `T2 ${fmtPct2(e.t2, ru)}`];
  if (e.cash != null) parts.push(`${ru ? 'кэш' : 'cash'} ${fmtPct2(e.cash, ru)}`);
  return parts.join(' · ');
}

/** The sentence pages use; falls back to an explicit «not measured», never to a list. */
export function holdingsSentence(ru = false, numbers = NUMBERS) {
  const list = protocolList(ru, numbers), tiers = tierSummary(ru, numbers);
  if (!list) return ru ? 'состав книги сейчас не измерен' : 'book composition not measured right now';
  return ru ? `${list}; итого ${tiers}` : `${list}; in total ${tiers}`;
}

export const NOT_MEASURED = { en: 'not measured', ru: 'не измерено' };
