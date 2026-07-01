/*
 * TimeToggle ⚙ — the ONE shared window selector: 1D / 7D / 30D / inception.
 * (Cockpit doctrine «history, not a number» — every series is viewable across windows.)
 *
 * 5-question map: the lens on "what happened" — reframes any history primitive (EquityChart,
 * AttributionWaterfall) across a time window. Pure client, controlled.
 *
 * Props:
 *   value    — active window key ('1D'|'7D'|'30D'|'ALL')
 *   onChange — (key) => void
 *   options  — override the set; default the four canonical windows
 *   lang, size
 */
import { MONO } from '../ui/tokens.js';

const DEFAULT = [
  { key: '1D', en: '1D', ru: '1Д' },
  { key: '7D', en: '7D', ru: '7Д' },
  { key: '30D', en: '30D', ru: '30Д' },
  { key: 'ALL', en: 'Inception', ru: 'С начала' },
];

export default function TimeToggle({ value = '7D', onChange, options = DEFAULT, lang = 'en', size = 'md' }) {
  const pad = size === 'sm' ? '4px 8px' : '5px 12px';
  const fs = size === 'sm' ? '.625rem' : '.6875rem';
  return (
    <div
      role="tablist"
      aria-label={lang === 'ru' ? 'Окно времени' : 'Time window'}
      style={{
        display: 'inline-flex', gap: 2, padding: 3, borderRadius: 'var(--r-full)',
        background: 'var(--bg-surface-2)', border: '1px solid var(--border)',
      }}
    >
      {options.map((o) => {
        const active = o.key === value;
        return (
          <button
            key={o.key}
            role="tab"
            aria-selected={active}
            onClick={() => onChange && onChange(o.key)}
            style={{
              fontFamily: MONO, fontSize: fs, fontWeight: active ? 600 : 500, padding: pad,
              borderRadius: 'var(--r-full)', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
              background: active ? 'var(--accent-bg)' : 'transparent',
              color: active ? 'var(--accent-hover)' : 'var(--text-muted)',
              transition: 'color 120ms ease, background 120ms ease',
            }}
          >
            {lang === 'ru' ? o.ru : o.en}
          </button>
        );
      })}
    </div>
  );
}
