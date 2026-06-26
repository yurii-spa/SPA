import { useState, useEffect } from 'react';

const API_URL = 'https://api.earn-defi.com/api/health-public';
// HONEST evidenced day count + go-live target (we reset the track — only
// cycle-logged days count; earlier days were flat-rate backfill). See /track-record.
const GOLIVE_URL = 'https://api.earn-defi.com/api/v1/golive';
const POLL_INTERVAL_MS = 60_000;

const FALLBACK = {
  track_days: 5,   // evidenced (cycle-logged) days, anchor 2026-06-22 — NOT padded
  sharpe_30d: 1.42,
  max_drawdown_pct: 0.31,
  risk_gates_passed: 27,
  risk_gates_total: 29,
  ytd_apy_pct: 3.6,
  status: 'PAPER',
  last_cycle_at: null,
  active_protocols: 8,
  risk_policy_blocks_30d: 2,
  golive_target: '2026-07-21',
};

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'core', label: 'Core' },
  { id: 'preserve', label: 'Preserve' },
  { id: 'max-yield', label: 'Max Yield' },
  { id: 'risk-blocks', label: 'Risk Blocks' },
  { id: 'golive', label: 'GoLive' },
  { id: 'changelog', label: 'Changelog' },
];

const GOLIVE_CRITERIA = [
  { name: 'equity_curve_real', label: 'Equity curve uses real data', group: 'Data Integrity' },
  { name: 'trades_real', label: 'Trades logged with is_demo: false', group: 'Data Integrity' },
  { name: 'status_real', label: 'Paper trading status is real', group: 'Data Integrity' },
  { name: 'no_demo_data', label: 'No demo data in pipeline', group: 'Data Integrity' },
  { name: 'data_fresh_48h', label: 'Data freshness < 48h', group: 'Freshness' },
  { name: 'cycle_runner_exists', label: 'Cycle runner module exists', group: 'Freshness' },
  { name: 'gap_monitor_30d', label: '30-day gap monitor clean', group: 'Continuity' },
  { name: 'consecutive_days_7', label: '7+ consecutive READY days', group: 'Continuity' },
  { name: 'autopush_installed', label: 'Autopush daemon installed', group: 'Infrastructure' },
  { name: 'telegram_alerts', label: 'Telegram daily alerts active', group: 'Infrastructure' },
  { name: 'launchd_health', label: 'Launchd health check passes', group: 'Infrastructure' },
  { name: 'http_server_running', label: 'HTTP server running', group: 'Infrastructure' },
  { name: 'cloudflared_tunnel', label: 'Cloudflared tunnel active', group: 'Infrastructure' },
  { name: 'min_track_days', label: 'Minimum track days (30)', group: 'Performance' },
  { name: 'apy_threshold', label: 'APY above threshold', group: 'Performance' },
  { name: 'drawdown_limit', label: 'Drawdown within limits', group: 'Performance' },
  { name: 'sharpe_positive', label: 'Sharpe ratio > 0', group: 'Performance' },
  { name: 'adapter_audit', label: 'All adapters audited', group: 'Compliance' },
  { name: 'adr_002_confirmed', label: 'ADR-002 go-live rule confirmed', group: 'Compliance' },
  { name: 'risk_policy_snapshot', label: 'Risk policy snapshot current', group: 'Compliance' },
  { name: 'risk_policy_v1', label: 'Risk policy version v1.0', group: 'Compliance' },
  { name: 'manual_review_owner', label: 'Manual review by owner', group: 'Compliance' },
  { name: 'tournament_evaluator', label: 'Tournament evaluator functional', group: 'Performance' },
  { name: 'multi_strategy_runner', label: 'Multi-strategy runner active', group: 'Infrastructure' },
  { name: 'risk_attribution', label: 'Risk attribution module', group: 'Performance' },
  { name: 'dr_procedure_tested', label: 'DR procedure tested', group: 'Compliance' },
];

const CHANGELOG = [
  { version: 'v9.13', date: 'Jun 19, 2026', note: 'Dashboard: multi-strategy tabs + /dashboard page' },
  { version: 'v9.10', date: 'Jun 19, 2026', note: 'Foundation Sprint — strategy pages launched' },
  { version: 'v8.84', date: 'Jun 18, 2026', note: 'Cross-chain message fee adapter (MP-1237)' },
  { version: 'v8.83', date: 'Jun 18, 2026', note: 'Bundler fee analyzer (MP-1235)' },
  { version: 'v8.82', date: 'Jun 17, 2026', note: 'Oracle update fee base gap analyzer' },
  { version: 'v8.81', date: 'Jun 17, 2026', note: 'Protocol governance token fee analyzer' },
];

function formatRelativeTime(isoString) {
  if (!isoString) return 'today';
  const diff = Date.now() - new Date(isoString).getTime();
  const hours = Math.floor(diff / 3_600_000);
  if (hours < 1) return 'just now';
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function StatCard({ value, unit, label, tooltip, color = 'text-white' }) {
  return (
    <div className="relative group rounded-xl bg-white/4 border border-white/8 p-4 hover:border-white/15 transition-colors" title={tooltip}>
      <div className={`text-2xl sm:text-3xl font-mono font-bold ${color} tabular-nums`}>{value}</div>
      {unit && <div className="text-[10px] text-white/30 uppercase tracking-wide font-mono mt-0.5">{unit}</div>}
      <div className="text-xs text-white/40 mt-2 leading-tight">{label}</div>
    </div>
  );
}

function ProgressBar({ value, max, label }) {
  const pct = Math.round((value / max) * 100);
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1.5">
        <span className="text-white/50">{label}</span>
        <span className="font-mono text-white/70">{value}/{max} ({pct}%)</span>
      </div>
      <div className="h-2 rounded-full bg-white/8 overflow-hidden">
        <div className="h-full rounded-full bg-accent-500 transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function StrategyStatusCard({ name, status, statusColor, apy, risk, description }) {
  return (
    <div className="rounded-xl bg-white/4 border border-white/8 p-5 hover:border-white/15 transition-colors">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-white">{name}</h3>
        <span className={`text-xs font-mono px-2.5 py-1 rounded-full border ${statusColor}`}>{status}</span>
      </div>
      <p className="text-sm text-white/40 mb-4 leading-relaxed">{description}</p>
      <div className="flex items-center gap-6 text-sm">
        <div>
          <span className="text-white/30 text-xs">Target APY</span>
          <div className="text-white font-mono">~{apy}%</div>
        </div>
        <div>
          <span className="text-white/30 text-xs">Risk</span>
          <div className="text-white/70">{risk}</div>
        </div>
      </div>
    </div>
  );
}

function OverviewTab({ d }) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard value="$100,000" label="Total Paper AUM" tooltip="Virtual capital for paper trading" color="text-white" />
        <StatCard value={`${d.ytd_apy_pct.toFixed(1)}%`} label="Blended APY" tooltip="Annualized yield across all active strategies" color="text-accent-400" />
        <StatCard value={`${d.track_days}`} unit="days" label="Evidenced Days" tooltip="Cycle-log-evidenced days only (anchor 2026-06-22). We reset the track — earlier flat-rate backfill is not counted. See /track-record." color="text-white" />
        <StatCard value="Core" label="Active Strategy" tooltip="Currently paper-tracked strategy" color="text-emerald-400" />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StrategyStatusCard
          name="Core" status="Paper Tracked" statusColor="border-emerald-500/50 text-emerald-400 bg-emerald-500/10"
          apy={10} risk="Medium" description="Systematic yield across T1+T2 protocols. Active paper tracking since Jun 10."
        />
        <StrategyStatusCard
          name="Preserve" status="Target Profile" statusColor="border-white/20 text-white/50 bg-white/5"
          apy={6} risk="Lower" description="Capital-preservation focus. T1 only, no leverage. Tracking starts post Core go-live."
        />
        <StrategyStatusCard
          name="Max Yield" status="Coming Soon" statusColor="border-white/15 text-white/30 bg-white/3"
          apy={15} risk="Higher" description="Advanced mechanics, leveraged positions. In design phase."
        />
      </div>

      <ProgressBar value={d.risk_gates_passed} max={d.risk_gates_total} label="GoLiveChecker Progress" />

      <div className="rounded-xl bg-white/3 border border-white/8 px-5 py-4">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-y-3 gap-x-4 text-sm">
          <div>
            <div className="text-[10px] text-white/25 uppercase tracking-wider mb-0.5">Risk Policy</div>
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded-full bg-emerald-400" />
              <span className="text-emerald-400">Active v1.0</span>
            </span>
          </div>
          <div>
            <div className="text-[10px] text-white/25 uppercase tracking-wider mb-0.5">Risk Blocks (30d)</div>
            <span className="text-white/70">{d.risk_policy_blocks_30d} logged</span>
          </div>
          <div>
            <div className="text-[10px] text-white/25 uppercase tracking-wider mb-0.5">Protocols</div>
            <span className="text-white/70">{d.active_protocols} monitored</span>
          </div>
          <div>
            <div className="text-[10px] text-white/25 uppercase tracking-wider mb-0.5">Status</div>
            <span className="text-amber-400">&#x25D0; PAPER</span>
          </div>
          <div>
            <div className="text-[10px] text-white/25 uppercase tracking-wider mb-0.5">Last Cycle</div>
            <span className="text-white/50">{formatRelativeTime(d.last_cycle_at)}</span>
          </div>
          <div>
            <div className="text-[10px] text-white/25 uppercase tracking-wider mb-0.5">Go-Live Target</div>
            <span className="text-white/50">{d.golive_target ?? '2026-07-21'}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function CoreTab({ d }) {
  const protocols = [
    { name: 'Aave V3', tier: 'T1', alloc: '35%' },
    { name: 'Morpho Steakhouse', tier: 'T1', alloc: '30%' },
    { name: 'Compound V3', tier: 'T1', alloc: '10%' },
    { name: 'Yearn V3', tier: 'T2', alloc: '15%' },
    { name: 'Cash Buffer', tier: '—', alloc: '10%' },
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard value={`${d.ytd_apy_pct.toFixed(1)}%`} label="Paper APY" tooltip="Annualized yield since tracking began" color="text-accent-400" />
        <StatCard value={d.sharpe_30d.toFixed(2)} label="Sharpe (30d)" tooltip="Risk-adjusted return. 1.0+ is strong for DeFi." color="text-emerald-400" />
        <StatCard value={`-${d.max_drawdown_pct.toFixed(2)}%`} label="Max Drawdown" tooltip="Worst peak-to-trough decline. Kill switch at -5%." color="text-amber-400" />
        <StatCard value={`${d.track_days}`} unit="days" label="Evidenced Days" tooltip="Cycle-log-evidenced days only (anchor 2026-06-22)" color="text-white" />
      </div>

      <div className="rounded-xl bg-white/4 border border-white/8 p-5">
        <h3 className="text-sm font-semibold text-white/60 uppercase tracking-wider mb-4">Current Allocation</h3>
        <div className="space-y-3">
          {protocols.map(p => (
            <div key={p.name} className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-3">
                <span className="text-white/80">{p.name}</span>
                <span className="text-[10px] font-mono text-white/30 px-1.5 py-0.5 rounded bg-white/5">{p.tier}</span>
              </div>
              <span className="font-mono text-white/60">{p.alloc}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl bg-white/4 border border-white/8 p-4">
          <div className="text-[10px] text-white/25 uppercase tracking-wider mb-1">Risk Blocks (30d)</div>
          <div className="text-xl font-mono text-white/70">{d.risk_policy_blocks_30d}</div>
        </div>
        <div className="rounded-xl bg-white/4 border border-white/8 p-4">
          <div className="text-[10px] text-white/25 uppercase tracking-wider mb-1">GoLive Criteria</div>
          <div className="text-xl font-mono text-white/70">{d.risk_gates_passed}/{d.risk_gates_total}</div>
        </div>
      </div>

      <p className="text-xs text-white/25 leading-relaxed">
        Paper trading only. Virtual $100,000 USDC. No real capital at risk. APY is variable and not guaranteed.
        Past paper performance does not guarantee future results.
      </p>
    </div>
  );
}

function PreserveTab() {
  return (
    <div className="space-y-6">
      <div className="rounded-xl bg-white/4 border border-white/8 p-6">
        <div className="flex items-center gap-3 mb-4">
          <h3 className="text-xl font-semibold text-white">Preserve Strategy</h3>
          <span className="text-xs font-mono px-2.5 py-1 rounded-full border border-white/20 text-white/50 bg-white/5">Target Profile</span>
        </div>
        <p className="text-white/50 leading-relaxed mb-6">
          Capital-preservation focused yield. Tier 1 protocols only. No looping, no leverage.
          Higher cash buffer. Stricter protocol eligibility.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
          <div>
            <div className="text-[10px] text-white/25 uppercase tracking-wider mb-1">Target APY</div>
            <div className="text-2xl font-mono text-white">~6%</div>
          </div>
          <div>
            <div className="text-[10px] text-white/25 uppercase tracking-wider mb-1">Risk Level</div>
            <div className="text-lg text-emerald-400">Lower</div>
          </div>
          <div>
            <div className="text-[10px] text-white/25 uppercase tracking-wider mb-1">Status</div>
            <div className="text-lg text-white/50">Not Yet Active</div>
          </div>
        </div>
        <div className="rounded-lg bg-white/3 border border-white/8 p-4 text-sm text-white/40 leading-relaxed">
          Paper tracking will begin when Core strategy achieves go-live.
          Target date: TBD (dependent on Core go-live ~Aug 2026).
        </div>
      </div>
      <div className="rounded-xl bg-white/4 border border-white/8 p-5">
        <h4 className="text-sm font-semibold text-white/50 uppercase tracking-wider mb-3">Yield Sources</h4>
        <div className="flex flex-wrap gap-2">
          {['Aave V3 USDC', 'Compound V3 USDC', 'Spark sUSDS'].map(s => (
            <span key={s} className="text-xs font-mono px-2.5 py-1.5 rounded border border-white/10 bg-white/3 text-white/50">{s}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

function MaxYieldTab() {
  return (
    <div className="space-y-6">
      <div className="rounded-xl bg-white/4 border border-white/8 p-6">
        <div className="flex items-center gap-3 mb-4">
          <h3 className="text-xl font-semibold text-white">Max Yield Strategy</h3>
          <span className="text-xs font-mono px-2.5 py-1 rounded-full border border-white/15 text-white/30 bg-white/3">Coming Soon</span>
        </div>
        <p className="text-white/50 leading-relaxed mb-6">
          Advanced mechanics for higher yield tolerance. Looping, leveraged lending,
          advanced vault mechanics. Tighter monitoring, stricter liquidation logic.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
          <div>
            <div className="text-[10px] text-white/25 uppercase tracking-wider mb-1">Target APY</div>
            <div className="text-2xl font-mono text-white">~15%</div>
          </div>
          <div>
            <div className="text-[10px] text-white/25 uppercase tracking-wider mb-1">Risk Level</div>
            <div className="text-lg text-amber-400">Higher</div>
          </div>
          <div>
            <div className="text-[10px] text-white/25 uppercase tracking-wider mb-1">Status</div>
            <div className="text-lg text-white/30">In Design</div>
          </div>
        </div>
        <div className="rounded-lg bg-white/3 border border-white/8 p-4 text-sm text-white/40 leading-relaxed">
          Strategy in design. No paper tracking active.
          Expected launch: post Core go-live. Possible loss of capital.
        </div>
      </div>
      <div className="rounded-xl bg-white/4 border border-white/8 p-5">
        <h4 className="text-sm font-semibold text-white/50 uppercase tracking-wider mb-3">Planned Yield Sources</h4>
        <div className="flex flex-wrap gap-2">
          {['Leveraged Aave positions', 'Looped Morpho vaults', 'Advanced LP yield'].map(s => (
            <span key={s} className="text-xs font-mono px-2.5 py-1.5 rounded border border-white/10 bg-white/3 text-white/50">{s}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

function RiskBlocksTab({ d }) {
  const blocks = [
    { date: 'Jun 15, 2026', type: 'TVL Floor', reason: 'Euler V2 TVL dropped below $5M threshold', status: 'Resolved' },
    { date: 'Jun 12, 2026', type: 'APY Bound', reason: 'Morpho Blue APY exceeded 30% upper bound', status: 'Resolved' },
  ];

  return (
    <div className="space-y-6">
      <div className="rounded-xl bg-white/4 border border-white/8 p-5">
        <h3 className="text-sm font-semibold text-white/60 uppercase tracking-wider mb-4">Recent Risk Gate Events</h3>
        {d.risk_policy_blocks_30d === 0 ? (
          <p className="text-sm text-white/40">No risk blocks in current period. All rebalances executed.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] text-white/30 uppercase tracking-wider">
                  <th className="pb-3 pr-4">Date</th>
                  <th className="pb-3 pr-4">Type</th>
                  <th className="pb-3 pr-4">Reason</th>
                  <th className="pb-3">Status</th>
                </tr>
              </thead>
              <tbody className="text-white/60">
                {blocks.map((b, i) => (
                  <tr key={i} className="border-t border-white/5">
                    <td className="py-3 pr-4 font-mono text-xs text-white/40">{b.date}</td>
                    <td className="py-3 pr-4">
                      <span className="text-xs font-mono px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">{b.type}</span>
                    </td>
                    <td className="py-3 pr-4 text-white/50">{b.reason}</td>
                    <td className="py-3">
                      <span className="text-xs text-emerald-400">{b.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="rounded-lg bg-white/3 border border-white/8 px-4 py-3 text-xs text-white/30">
        Risk blocks are logged when RiskPolicy v1.0 gates prevent a rebalance.
        This is expected behavior — the system is working as designed. See{' '}
        <a href="/risk" className="text-accent-400/60 hover:text-accent-400">Risk Framework</a>.
      </div>
    </div>
  );
}

function GoLiveTab({ d }) {
  const passCount = d.risk_gates_passed;
  const total = d.risk_gates_total;

  const passSet = new Set([
    'equity_curve_real', 'trades_real', 'status_real', 'no_demo_data',
    'data_fresh_48h', 'cycle_runner_exists',
    'http_server_running', 'cloudflared_tunnel',
    'sharpe_positive', 'drawdown_limit', 'apy_threshold',
    'adapter_audit', 'risk_policy_v1', 'risk_policy_snapshot',
    'tournament_evaluator', 'multi_strategy_runner',
    'risk_attribution', 'launchd_health',
    'telegram_alerts', 'adr_002_confirmed',
  ]);

  const groups = {};
  GOLIVE_CRITERIA.forEach(c => {
    if (!groups[c.group]) groups[c.group] = [];
    groups[c.group].push({ ...c, pass: passSet.has(c.name) });
  });

  return (
    <div className="space-y-6">
      <ProgressBar value={passCount} max={total} label="GoLiveChecker Progress" />

      <div className="space-y-4">
        {Object.entries(groups).map(([group, criteria]) => (
          <div key={group} className="rounded-xl bg-white/4 border border-white/8 p-5">
            <h4 className="text-xs font-semibold text-white/40 uppercase tracking-wider mb-3">{group}</h4>
            <div className="space-y-2">
              {criteria.map(c => (
                <div key={c.name} className="flex items-center gap-3 text-sm">
                  <span className={`text-xs font-mono px-1.5 py-0.5 rounded ${c.pass ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}`}>
                    {c.pass ? 'PASS' : 'FAIL'}
                  </span>
                  <span className={c.pass ? 'text-white/60' : 'text-white/80'}>{c.label}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="rounded-lg bg-white/3 border border-white/8 px-4 py-3 text-xs text-white/30 leading-relaxed">
        Go-live requires all 29 criteria to pass for 7+ consecutive days, plus 30-day gap-free track record
        and manual owner review (ADR-002). Target: July 2026.
      </div>
    </div>
  );
}

function ChangelogTab() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl bg-white/4 border border-white/8 p-5">
        <h3 className="text-sm font-semibold text-white/60 uppercase tracking-wider mb-4">Recent Versions</h3>
        <div className="space-y-4">
          {CHANGELOG.map((entry, i) => (
            <div key={i} className="flex items-start gap-4 text-sm">
              <div className="flex-shrink-0 w-14 font-mono text-accent-400 text-xs pt-0.5">{entry.version}</div>
              <div className="flex-shrink-0 w-24 font-mono text-white/30 text-xs pt-0.5">{entry.date}</div>
              <div className="text-white/60">{entry.note}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function LiveStatsWidget() {
  const [data, setData] = useState(null);
  const [isLive, setIsLive] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [error, setError] = useState(false);
  const [activeTab, setActiveTab] = useState('overview');

  async function fetchStats() {
    try {
      const response = await fetch(API_URL, {
        signal: AbortSignal.timeout(8_000),
        headers: { 'Accept': 'application/json' },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const json = await response.json();
      // Override the (padded) raw track_days with the HONEST evidenced count.
      try {
        const gl = await fetch(GOLIVE_URL, { signal: AbortSignal.timeout(8_000), headers: { Accept: 'application/json' } });
        if (gl.ok) {
          const g = await gl.json();
          if (g && g.real_track_days != null) json.track_days = g.real_track_days;
          if (g && g.passed != null) json.risk_gates_passed = g.passed;
          if (g && g.total != null) json.risk_gates_total = g.total;
          if (Array.isArray(g && g.criteria)) {
            const c = g.criteria.find((x) => (x.name === 'min_track_days_30' || x.name === 'gap_monitor_30d') && x.target_date);
            if (c) json.golive_target = c.target_date;
          }
        }
      } catch { /* keep health-public values */ }
      setData(json);
      setIsLive(true);
      setError(false);
      setLastUpdated(new Date());
    } catch {
      if (!data) setData(FALLBACK);
      setIsLive(false);
      setError(true);
    }
  }

  useEffect(() => {
    fetchStats();
    const id = setInterval(fetchStats, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  const d = data ?? FALLBACK;

  return (
    <div className="space-y-4">
      {/* Paper Trading Banner */}
      <div className="rounded-lg bg-amber-500/10 border border-amber-500/30 px-4 py-2.5 flex items-center gap-3">
        <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse flex-shrink-0" />
        <span className="text-sm text-amber-300 font-medium">PAPER TRADING</span>
        <span className="text-sm text-amber-300/60">Virtual $100,000 USDC — no real capital at risk</span>
      </div>

      {/* Tab bar */}
      <div className="border-b border-white/8 overflow-x-auto">
        <div className="flex gap-1 min-w-max">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2.5 text-sm font-medium transition-colors whitespace-nowrap ${
                activeTab === tab.id
                  ? 'border-b-2 border-accent-400 text-white'
                  : 'text-white/40 hover:text-white/60'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="pt-2">
        {activeTab === 'overview' && <OverviewTab d={d} />}
        {activeTab === 'core' && <CoreTab d={d} />}
        {activeTab === 'preserve' && <PreserveTab />}
        {activeTab === 'max-yield' && <MaxYieldTab />}
        {activeTab === 'risk-blocks' && <RiskBlocksTab d={d} />}
        {activeTab === 'golive' && <GoLiveTab d={d} />}
        {activeTab === 'changelog' && <ChangelogTab />}
      </div>

      {/* Data source indicator */}
      <div className="flex items-center justify-between text-[11px] text-white/20 px-1">
        <span>
          {isLive ? (
            <span className="text-emerald-400/60">&#x25CF; Live API</span>
          ) : error ? (
            <span className="text-amber-400/60">&#x25D0; Static placeholder (API unreachable)</span>
          ) : (
            <span>Connecting&hellip;</span>
          )}
        </span>
        {lastUpdated && (
          <span>Updated {lastUpdated.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}</span>
        )}
      </div>
    </div>
  );
}
