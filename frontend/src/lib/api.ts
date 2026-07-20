/** Typed API client used by all views. */

export async function api<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    cache: 'no-store',
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText} ${text}`.trim())
  }
  return res.json() as Promise<T>
}

// ---- Types ----

export interface Profile {
  id: string
  name: string
  symbol: string
  exchange: string
  expiryKind: string
  expiryDate: string | null
  intervalMin: number
  templateId: string | null
  outputFormats: string
  enabled: boolean
  paused: boolean
  allStrikes: boolean
  notifyChannels: string
  lastRunAt: string | null
  nextRunAt: string | null
  lastStatus: string | null
  runCount: number
  failCount: number
  successCount: number
  avgDurationMs: number
  createdAt: string
  template?: { id: string; name: string } | null
}

export interface Report {
  id: string
  profileId: string
  symbol: string
  expiry: string
  spotPrice: number
  generatedAt: string
  pcr: number
  pcrVolume: number
  maxPain: number
  ivPut: number
  ivCall: number
  atmStrike: number
  totalCallOi: number
  totalPutOi: number
  totalCallVol: number
  totalPutVol: number
  callChgOi: number
  putChgOi: number
  trend: string
  trendScore: number
  support: number
  resistance: number
  reportHash: string
  profile?: { name: string; intervalMin: number }
}

export interface ReportDetail extends Report {
  indicators: Record<string, number | string>
  summary: Record<string, string>
  strikes: StrikeRow[]
}

export interface StrikeRow {
  strike: number
  ceLtp: number
  ceOi: number
  ceChgOi: number
  ceVolume: number
  ceIv: number
  peLtp: number
  peOi: number
  peChgOi: number
  peVolume: number
  peIv: number
}

export interface Execution {
  id: string
  profileId: string
  status: string
  stage: string
  startedAt: string
  finishedAt: string | null
  durationMs: number
  message: string | null
  error: string | null
  triggeredBy: string
  retries: number
  reportId: string | null
  profile?: { name: string; symbol: string }
}

export interface LogEntry {
  id: string
  executionId: string | null
  profileId: string | null
  level: string
  source: string
  message: string
  meta: string | null
  createdAt: string
  execution?: { profile: { symbol: string; name: string } } | null
}

export interface StatusResponse {
  counts: {
    profiles: number
    reports: number
    executions: number
    logs: number
    channels: number
    running: number
    failedToday: number
    successToday: number
    enabledProfiles: number
  }
  schedulerEnabled: boolean
  lastReport: { id: string; symbol: string; generatedAt: string; trend: string } | null
  upcoming: { id: string; name: string; symbol: string; nextRunAt: string; intervalMin: number }[]
}

export interface StatsResponse {
  totals: { total: number; success: number; failed: number; running: number; successRate: number }
  avgDurationMs: number
  timeline: { time: string; success: number; failed: number; running: number; avgMs: number; n: number }[]
  profiles: {
    id: string
    name: string
    symbol: string
    runCount: number
    successCount: number
    failCount: number
    avgDurationMs: number
    lastStatus: string | null
    successRate: number
  }[]
}

export interface HealthResponse {
  cpu: number
  memPct: number
  heapUsedMb: number
  heapTotalMb: number
  uptimeSec: number
  db: { profiles: number; reports: number; executions: number; logs: number }
  running: number
  failedLastHour: number
  marketOpen: boolean
  schedule: { start: string; end: string }
  portal: { url: string; timeout: string }
}

export interface Credential {
  id: string
  label: string
  portal: string
  username: string
  active: boolean
  lastUsed: string | null
  createdAt: string
  hasPassword: boolean
}

export interface NotificationChannel {
  id: string
  name: string
  type: string
  enabled: boolean
  config: string
  createdAt: string
}

export interface FormulaTemplate {
  id: string
  name: string
  description: string | null
  version: number
  enabled: boolean
  config: Record<string, unknown>
  createdAt: string
}

export interface User {
  id: string
  email: string
  name: string
  role: string
  active: boolean
  lastLogin: string | null
  createdAt: string
}

export interface NotificationLog {
  id: string
  channelId: string
  reportId: string | null
  profileId: string | null
  status: string
  message: string | null
  error: string | null
  createdAt: string
  channel?: { name: string; type: string }
}

// ---- Analytics types ----

export interface HistoryPoint {
  id: string
  symbol: string
  generatedAt: string
  spotPrice: number
  pcr: number
  pcrVolume: number
  maxPain: number
  ivCall: number
  ivPut: number
  atmStrike: number
  totalCallOi: number
  totalPutOi: number
  callChgOi: number
  putChgOi: number
  trend: string
  trendScore: number
  support: number
  resistance: number
}

export interface HistoryResponse {
  points: HistoryPoint[]
  bySymbol: Record<string, HistoryPoint[]>
  symbols: string[]
}

export interface SymbolAnalytics {
  symbol: string
  latest: Report
  points: HistoryPoint[]
  aggregates: {
    avgPcr: number
    avgMaxPain: number
    avgSpot: number
    spotRange: [number, number]
    ivCallRange: [number, number]
    ivPutRange: [number, number]
    trendDist: { bullish: number; bearish: number; neutral: number }
    spotChange: number
    spotChangePct: number
    pcrSlope: number
    sampleCount: number
  }
}

export interface TickerItem {
  symbol: string
  label: string
  spotPrice: number
  prevSpot: number
  change: number
  changePct: number
  pcr: number
  trend: string
  trendScore: number
  generatedAt: string
  maxPain: number
}

export interface CompareRow {
  id: string
  symbol: string
  generatedAt: string
  spotPrice: number
  pcr: number
  maxPain: number
  trend: string
  trendScore: number
  totalCallOi: number
  totalPutOi: number
  ivCall: number
  ivPut: number
  support: number
  resistance: number
}
