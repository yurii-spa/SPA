/**
 * SPA API client — два режима:
 *
 * DEV  (npm run dev):  proxy → localhost:8000  (FastAPI)
 * PROD (GitHub Pages): читает /SPA/data/*.json (статика, обновляется GitHub Actions каждые 4ч)
 *
 * Переменная окружения:
 *   VITE_STATIC_MODE=true   → принудительно статический режим
 *   VITE_API_URL=http://... → кастомный REST-бэкенд в production
 */

import type {
  StatusResponse,
  Protocol,
  Trade,
  BusStats,
  RunResponse,
  StrategyPoint,
  HealthResponse,
} from './types'

// В production без явного VITE_API_URL → статический режим
const IS_STATIC =
  import.meta.env.VITE_STATIC_MODE === 'true' ||
  (import.meta.env.PROD && !import.meta.env.VITE_API_URL)

const BASE = import.meta.env.VITE_API_URL ?? ''

// GitHub Pages base path — должен совпадать с vite.config.ts base
const STATIC_BASE = '/SPA/data'

// ─── Helpers ─────────────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`)
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText} — ${path}`)
  return resp.json() as Promise<T>
}

async function getStatic<T>(file: string): Promise<T> {
  const url = `${STATIC_BASE}/${file}?_=${Date.now()}`   // cache-bust
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`${resp.status} — ${url}`)
  return resp.json() as Promise<T>
}

async function getStaticOrDefault<T>(file: string, fallback: T): Promise<T> {
  try {
    return await getStatic<T>(file)
  } catch {
    return fallback
  }
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText} — ${path}`)
  return resp.json() as Promise<T>
}

// ─── API surface ──────────────────────────────────────────────────────────────

export const api = {
  isStatic: IS_STATIC,

  health: (): Promise<HealthResponse> =>
    IS_STATIC
      ? getStatic<{ updated_at: string; version: string; source: string }>('meta.json').then(
          (m) => ({ status: 'ok (static)', version: m.version, timestamp: m.updated_at }),
        )
      : get<HealthResponse>('/health'),

  status: (): Promise<StatusResponse> =>
    IS_STATIC ? getStatic<StatusResponse>('status.json') : get<StatusResponse>('/api/status'),

  protocols: (): Promise<Protocol[]> =>
    IS_STATIC ? getStatic<Protocol[]>('protocols.json') : get<Protocol[]>('/api/protocols'),

  trades: (_open_only = false): Promise<Trade[]> =>
    IS_STATIC
      ? getStaticOrDefault<Trade[]>('trades.json', [])
      : get<Trade[]>(`/api/trades?open_only=${_open_only}`),

  // bus_stats.json may not exist in static mode → return empty object gracefully
  busStats: (): Promise<BusStats> =>
    IS_STATIC
      ? getStaticOrDefault<BusStats>('bus_stats.json', {})
      : get<BusStats>('/api/bus/stats'),

  strategyState: (_limit = 48): Promise<StrategyPoint[]> =>
    IS_STATIC
      ? getStaticOrDefault<StrategyPoint[]>('strategy_state.json', [])
      : get<StrategyPoint[]>(`/api/strategy/state?limit=${_limit}`),

  // В статическом режиме "Run" недоступен — показываем сообщение
  run: (): Promise<RunResponse> =>
    IS_STATIC
      ? Promise.reject(new Error('Run not available in static mode — use local FastAPI server'))
      : post<RunResponse>('/api/run'),
}
