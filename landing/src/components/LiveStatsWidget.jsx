/**
 * LiveStatsWidget.jsx
 * React island — hydrates client:visible, polls API every 60 seconds.
 * Falls back to static placeholder data if API is unreachable.
 *
 * API endpoint: https://api.earn-defi.com/api/health-public
 * Expected response shape:
 * {
 *   track_days: number,           // e.g. 8
 *   sharpe_30d: number,           // e.g. 1.42
 *   max_drawdown_pct: number,     // e.g. 0.31 (positive; displayed as -0.31%)
 *   risk_gates_passed: number,    // e.g. 16
 *   risk_gates_total: number,     // e.g. 26
 *   ytd_apy_pct: number,          // e.g. 6.8
 *   status: "PAPER" | "LIVE",
 *   last_cycle_at: string,        // ISO timestamp
 *   active_protocols: number,
 *   risk_policy_blocks_30d: number,
 *   golive_target: string,        // e.g. "2026-08-01"
 * }
 */

import { useState, useEffect } from 'react';

const API_URL = 'https://api.earn-defi.com/api/health-public';
const POLL_INTERVAL_MS = 60_000;

// Static fallback data — shown when API is unreachable
const FALLBACK_DATA = {
  track_days: 8,
  sharpe_30d: 1.42,
  max_drawdown_pct: 0.31,
  risk_gates_passed: 16,
  risk_gates_total: 26,
  ytd_apy_pct: 6.8,
  status: 'PAPER',
  last_cycle_at: null,
  active_protocols: 8,
  risk_policy_blocks_30d: 2,
  golive_target: '2026-08-01',
};

function formatRelativeTime(isoString) {
  if (!isoString) return 'today';
  const diff = Date.now() - new Date(isoString).getTime();
  const hours = Math.floor(diff / 3_600_000);
  if (hours < 1) return 'just now';
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const METRICS = [
  {
    key: 'track_days',
    label: 'Track Days',
    format: (d) => `${d.track_days}`,
    unit: 'days',
    tooltip: 'Consecutive days of clean, logged track record since June 10, 2026.',
    color: 'text-white',
  },
  {
    key: 'sharpe_30d',
    label: 'Sharpe (30d)',
    format: (d) => d.sharpe_30d.toFixed(2),
    unit: '',
    tooltip: 'Risk-adjusted return: higher is better. 1.0+ considered strong for DeFi strategies.',
    color: 'text-emerald-400',
  },
  {
    key: 'max_drawdown_pct',
    label: 'Max Drawdown',
    format: (d) => `-${d.max_drawdown_pct.toFixed(2)}%`,
    unit: '',
    tooltip: 'Worst peak-to-trough decline. Kill switch triggers at -5%. Negative months shown — we do not cherry-pick.',
    color: 'text-amber-400',
  },
  {
    key: 'ytd_apy_pct',
    label: 'YTD APY',
    format: (d) => `${d.ytd_apy_pct.toFixed(1)}%`,
    unit: '',
    tooltip: 'Year-to-date annualized yield. Paper trading — simulated performance only.',
    color: 'text-accent-400',
  },
  {
    key: 'risk_gates',
    label: 'Go-Live Criteria',
    format: (d) => `${d.risk_gates_passed}/${d.risk_gates_total}`,
    unit: 'passed',
    tooltip: 'GoLiveChecker: 26 criteria must pass before real capital is deployed (ADR-002).',
    color: 'text-white/70',
  },
];

const SECONDARY = [
  {
    label: 'Risk Policy',
    render: () => (
      <span className="flex items-center gap-1.5">
        <span className="inline-block w-2 h-2 rounded-full bg-emerald-400" />
        <span className="text-emerald-400">Active v1.0</span>
      </span>
    ),
  },
  {
    label: 'Risk Blocks (30d)',
    render: (d) => (
      <span className="text-white/70">{d.risk_policy_blocks_30d} logged</span>
    ),
  },
  {
    label: 'Protocols',
    render: (d) => (
      <span className="text-white/70">{d.active_protocols} monitored</span>
    ),
  },
  {
    label: 'Status',
    render: (d) => (
      <span className={d.status === 'LIVE' ? 'text-emerald-400 font-semibold' : 'text-amber-400'}>
        {d.status === 'LIVE' ? '● LIVE' : '◐ PAPER'}
      </span>
    ),
  },
  {
    label: 'Last Cycle',
    render: (d) => (
      <span className="text-white/50">{formatRelativeTime(d.last_cycle_at)}</span>
    ),
  },
  {
    label: 'Go-Live Target',
    render: (d) => (
      <span className="text-white/50">{d.golive_target ?? '2026-08-01'}</span>
    ),
  },
];

export default function LiveStatsWidget() {
  const [data, setData] = useState(null);
  const [isLive, setIsLive] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [error, setError] = useState(false);

  async function fetchStats() {
    try {
      const response = await fetch(API_URL, {
        signal: AbortSignal.timeout(8_000),
        headers: { 'Accept': 'application/json' },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const json = await response.json();
      setData(json);
      setIsLive(true);
      setError(false);
      setLastUpdated(new Date());
    } catch {
      // API unreachable — use fallback, don't crash
      if (!data) setData(FALLBACK_DATA);
      setIsLive(false);
      setError(true);
    }
  }

  useEffect(() => {
    fetchStats();
    const id = setInterval(fetchStats, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  const displayData = data ?? FALLBACK_DATA;

  return (
    <div className="space-y-4">
      {/* Primary metrics grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {METRICS.map(({ key, label, format, unit, tooltip, color }) => (
          <div
            key={key}
            className="relative group rounded-xl bg-white/4 border border-white/8 p-4 hover:border-white/15 transition-colors"
            title={tooltip}
          >
            <div className={`text-2xl sm:text-3xl font-mono font-bold ${color} tabular-nums`}>
              {format(displayData)}
            </div>
            {unit && (
              <div className="text-[10px] text-white/30 uppercase tracking-wide font-mono mt-0.5">
                {unit}
              </div>
            )}
            <div className="text-xs text-white/40 mt-2 leading-tight">{label}</div>

            {/* Tooltip on hover */}
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-52 p-2.5 rounded-lg bg-[#1a1a2e] border border-white/10 text-xs text-white/60 leading-relaxed opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10 hidden sm:block">
              {tooltip}
            </div>
          </div>
        ))}
      </div>

      {/* Secondary row */}
      <div className="rounded-xl bg-white/3 border border-white/8 px-5 py-4">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-y-3 gap-x-4 text-sm">
          {SECONDARY.map(({ label, render }) => (
            <div key={label}>
              <div className="text-[10px] text-white/25 uppercase tracking-wider mb-0.5">{label}</div>
              <div>{render(displayData)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Data source indicator */}
      <div className="flex items-center justify-between text-[11px] text-white/20 px-1">
        <span>
          {isLive ? (
            <span className="text-emerald-400/60">● Live API</span>
          ) : error ? (
            <span className="text-amber-400/60">◐ Static placeholder (API unreachable)</span>
          ) : (
            <span>Connecting…</span>
          )}
        </span>
        {lastUpdated && (
          <span>Updated {lastUpdated.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}</span>
        )}
      </div>
    </div>
  );
}
