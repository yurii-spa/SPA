// golive_label.js — the ONE honest source for the public go-live wording (2026-09-08).
//
// Why this exists. `track_snapshot.go_live_target` (and the live `/api/v1/golive.target_date`)
// is a CALENDAR ESTIMATE the gate computes as anchor + 29 days = 2026-07-21. It was true as an
// ETA while the 30-day track was accumulating; once the track passed 30 days the date stayed
// baked into ≥13 pages as if it were still ahead ("~July 2026", "0 days remaining"). Go-live is
// an OWNER DECISION, not a calendar item — the snapshot carries no owner-set date, so none is
// shown. A date is rendered ONLY while it is still in the future relative to the snapshot's
// `as_of` (or the caller's clock on the client); otherwise the honest state is spelled out.
//
// Used server-side by the .astro pages (build-time snapshot) and client-side by the React
// dashboard island (live facts). Inline `<script is:inline>` blocks cannot import modules —
// they apply the same "future-only" rule by hand (see track-record.astro loadGoLive).
//
// No promises are added here: the strings say what is measured (days, gates) and that the date
// is not set. Nothing in this file is a yield number, a tier name or legal copy.

const DAYS_NEEDED_DEFAULT = 30;

function isoDay(v) {
  if (typeof v !== 'string') return null;
  const m = v.match(/^\d{4}-\d{2}-\d{2}/);
  return m ? m[0] : null;
}

/**
 * @param {object} snap  — track_snapshot-shaped facts: { go_live_target, as_of, generated_at,
 *                         real_track_days, days_needed }
 * @param {string} [now] — ISO day (YYYY-MM-DD) to judge "is the date still ahead"; defaults
 *                         to snap.as_of, then snap.generated_at.
 */
export function goLiveLabel(snap, now) {
  const s = snap || {};
  const target = isoDay(s.go_live_target);
  const asOf = isoDay(now) || isoDay(s.as_of) || isoDay(s.generated_at);
  const needed = Number.isFinite(Number(s.days_needed)) && s.days_needed != null
    ? Number(s.days_needed) : DAYS_NEEDED_DEFAULT;
  const daysRaw = s.real_track_days != null ? Number(s.real_track_days) : null;
  const days = Number.isFinite(daysRaw) ? daysRaw : null;
  const gatePassed = days != null && days >= needed;
  // A date counts as "set" only while it is ahead of the evidence we are judging it against.
  const dateSet = !!target && !!asOf && target > asOf;
  const dTxt = days != null ? String(days) : '—';

  if (dateSet) {
    return {
      dateSet: true, target, days, needed, gatePassed,
      en: `go-live target: ${target}`,
      ru: `цель go-live: ${target}`,
      shortEn: target,
      shortRu: target,
    };
  }
  if (gatePassed) {
    const en = `decision pending — ${needed}-day gate passed (${dTxt}/${needed}), date not set`;
    const ru = `решение владельца ожидается — ${needed}-дневный порог пройден (${dTxt}/${needed}), дата не назначена`;
    return {
      dateSet: false, target: null, days, needed, gatePassed,
      en: `go-live: ${en}`,
      ru: `go-live: ${ru}`,
      shortEn: en,
      shortRu: ru,
    };
  }
  const en = `date not set — ${dTxt}/${needed} evidenced days toward the ${needed}-day gate`;
  const ru = `дата не назначена — ${dTxt}/${needed} подтверждённых дней до ${needed}-дневного порога`;
  return {
    dateSet: false, target: null, days, needed, gatePassed,
    en: `go-live: ${en}`,
    ru: `go-live: ${ru}`,
    shortEn: en,
    shortRu: ru,
  };
}

/**
 * The date on which the N-th evidenced day was logged (N = snap.days_needed, default 30) —
 * i.e. when the time gate actually closed — read from the snapshot's OWN bars. null while the
 * gate is still open or the bars are absent. One definition, shared by /status and the blog note.
 */
export function gateClosedOn(snap) {
  const s = snap || {};
  const needed = Number.isFinite(Number(s.days_needed)) && s.days_needed != null
    ? Number(s.days_needed) : DAYS_NEEDED_DEFAULT;
  const bars = Array.isArray(s.bars) ? s.bars.filter((b) => b && b.evidenced === true) : [];
  if (bars.length < needed || needed < 1) return null;
  return isoDay(bars[needed - 1].date);
}

/**
 * P1-6/7/8 (2026-10-08): the ONE sentence about the 30-day time gate and what remains, derived from
 * the snapshot — never «accruing to 30» / «thin» typed into a page that outlives the gate. While the
 * gate is open it says so with the live count; once passed it says the minimum is met and names
 * what still blocks live capital (owner decision + legal review; custody and audit for the live phase).
 */
export function trackGateSentence(snap, ru = false) {
  const g = goLiveLabel(snap);
  const d = g.days != null ? String(g.days) : '—';
  if (g.gatePassed) {
    return ru
      ? `Минимум в ${g.needed} подтверждённых дней пройден (${d}/${g.needed}); засчитываются только дни с реальным логом ежедневного цикла. Для реального капитала по-прежнему нужны решение владельца и юридическая проверка, а для live-этапа — хранение средств (кастоди) и аудит.`
      : `The ${g.needed}-evidenced-day minimum is met (${d}/${g.needed}); only days with a real daily-cycle log count. Live capital still needs an owner decision and a legal review, and the live phase needs custody and an audit.`;
  }
  return ru
    ? `Трек накапливается: ${d}/${g.needed} подтверждённых дней; засчитываются только дни с реальным логом ежедневного цикла. До ${g.needed}-го дня метрики риска помечены как предварительные, а не выдуманы.`
    : `The track is accruing: ${d}/${g.needed} evidenced days; only days with a real daily-cycle log count. Until day ${g.needed} risk-adjusted ratios are marked preliminary, never fabricated.`;
}

/** Short blocker list for meta descriptions (no numbers that can go stale). */
export function remainingBlockers(snap, ru = false) {
  const g = goLiveLabel(snap);
  if (g.gatePassed) return ru ? 'решение владельца, юридическая проверка, кастоди и аудит' : 'an owner decision, a legal review, custody and an audit';
  return ru ? `кастоди, аудит, юридическая проверка и ${g.needed}-дневный трек` : `custody, audit, legal review and the ${g.needed}-day evidenced track`;
}
