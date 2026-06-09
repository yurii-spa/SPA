// ─── API response types ───────────────────────────────────────────────────────

export interface Portfolio {
  total_capital_usd: number
  deployed_usd: number
  cash_usd: number
  cash_pct: number
  total_pnl_usd: number
  total_drawdown_pct: number
}

export interface Position {
  protocol_key: string
  tier: 'T1' | 'T2'
  amount_usd: number
  current_apy: number
  unrealized_pnl_usd: number
  unrealized_pnl_pct: number
  days_held: number
}

export interface RiskInfo {
  health_approved: boolean
  violations: string[]
  warnings: string[]
  var_usd: number
  var_pct: number
  var_breach: boolean
}

export interface PaperTradingClock {
  days_elapsed: number
  weeks_elapsed: number
  min_weeks_required: number
  go_live_ready: boolean
  first_trade: string | null
}

export interface StatusResponse {
  timestamp: string
  portfolio: Portfolio
  positions: Position[]
  risk: RiskInfo
  paper_trading: PaperTradingClock
  strategy: Record<string, unknown>
}

export interface Protocol {
  key: string
  protocol: string
  asset: string
  chain: string
  tier: 'T1' | 'T2'
  is_active: number
  apy_total: number | null
  apy_base: number | null
  apy_reward: number | null
  tvl_usd: number | null
  last_snapshot: string | null
}

export interface Trade {
  trade_id: string
  strategy_id: string
  timestamp_open: string
  timestamp_close: string | null
  protocol_key: string
  asset: string
  action: 'OPEN' | 'CLOSE' | 'REBALANCE'
  amount_usd: number
  apy_at_open: number | null
  net_apy_annualized: number | null
  pnl_usd: number | null
}

export interface BusTopicStats {
  pending: number
  consumed: number
  acked: number
  dead: number
}

export type BusStats = Record<string, BusTopicStats>

export interface RunResponse {
  iteration: number
  timestamp: string
  fetch_ok: boolean
  blocked: boolean
  signals: number
  decisions: number
  executions: number
  errors: string[]
  bus_stats: BusStats
}

export interface StrategyPoint {
  timestamp: string
  total_capital_usd: number
  deployed_capital_usd: number
  cash_usd: number
  total_pnl_usd: number
  total_pnl_pct: number
  current_apy: number | null
  trade_count: number
}

export interface HealthResponse {
  status: string
  version: string
  timestamp: string
}
