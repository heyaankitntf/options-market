'use client'

import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Activity, FileBarChart, Workflow, CheckCircle2, AlertTriangle, Cpu,
  Database, Clock, TrendingUp, TrendingDown, ArrowRight, Zap, Target,
  PlayCircle, PauseCircle,
} from 'lucide-react'
import {
  Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid,
  BarChart, Bar, Cell,
} from 'recharts'
import { api, type StatusResponse, type HealthResponse, type StatsResponse, type Report, type Execution } from '@/lib/api'
import { fmtNum, fmtOI, fmtDateTime, relTime, fmtPct } from '@/lib/format'
import { StatCard, SectionHeader, TrendBadge, StatusBadge, LiveDot, EmptyState, MiniBar } from '@/components/ui/primitives'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'

export function DashboardView({ status, health }: { status: StatusResponse | null; health: HealthResponse | null }) {
  const stats = useQuery({ queryKey: ['stats'], queryFn: () => api<StatsResponse>('/api/stats'), refetchInterval: 15000 })
  const reports = useQuery({
    queryKey: ['reports-latest'],
    queryFn: () => api<Report[]>('/api/reports?limit=6'),
    refetchInterval: 12000,
  })
  const executions = useQuery({
    queryKey: ['executions-recent'],
    queryFn: () => api<Execution[]>('/api/executions?limit=8'),
    refetchInterval: 8000,
  })

  const c = status?.counts
  const successRate = stats.data?.totals.successRate ?? 0

  return (
    <div className="space-y-6">
      {/* Hero status band */}
      <div className="rounded-2xl border bg-gradient-to-br from-card via-card/60 to-card/30 p-5 lg:p-6 relative overflow-hidden glow-primary">
        <div className="absolute inset-0 grid-bg opacity-30" />
        <div className="absolute -top-12 -right-12 h-48 w-48 rounded-full bg-primary/8 blur-3xl" />
        <div className="relative flex flex-col lg:flex-row lg:items-center justify-between gap-5">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <LiveDot />
              <span className="text-xs font-medium text-emerald-500 uppercase tracking-wider">Live Automation</span>
              <span className="text-xs text-muted-foreground/60">·</span>
              <span className="text-xs text-muted-foreground">
                {health?.marketOpen ? 'Market hours active' : 'Outside market hours'}
              </span>
            </div>
            <h2 className="text-2xl lg:text-3xl font-bold tracking-tight">
              {c?.enabledProfiles ?? 0} <span className="text-primary">profiles</span>{' '}
              <span className="text-muted-foreground font-normal">automating</span>
            </h2>
            <p className="text-sm text-muted-foreground mt-1.5">
              <span className="tnum text-foreground/80 font-medium">{c?.reports ?? 0}</span> reports ·{' '}
              <span className="tnum text-foreground/80 font-medium">{c?.executions ?? 0}</span> executions ·{' '}
              scheduler <span className={status?.schedulerEnabled ? 'text-emerald-500' : 'text-amber-500'}>{status?.schedulerEnabled ? 'active' : 'paused'}</span>
            </p>
            {/* Inline mini-stats */}
            <div className="flex items-center gap-4 mt-3">
              <MiniPill label="Success" value={`${successRate}%`} tone={successRate > 90 ? 'emerald' : successRate > 70 ? 'amber' : 'rose'} />
              <MiniPill label="Failed today" value={String(c?.failedToday ?? 0)} tone={(c?.failedToday ?? 0) > 0 ? 'rose' : 'muted'} />
              <MiniPill label="Running" value={String(c?.running ?? 0)} tone={(c?.running ?? 0) > 0 ? 'sky' : 'muted'} />
            </div>
          </div>
          <div className="flex items-center gap-4 shrink-0">
            <HeroSparkline />
            <div className="h-16 w-px bg-border" />
            <Donut value={successRate} label="Success rate" />
            <div className="h-16 w-px bg-border" />
            <div className="space-y-1">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Last report</div>
              <div className="font-semibold tnum text-sm">{status?.lastReport ? relTime(status.lastReport.generatedAt) : '—'}</div>
              <div className="text-xs text-muted-foreground">{status?.lastReport?.symbol ?? 'awaiting first run'}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-4">
        <StatCard
          label="Active Profiles"
          value={c?.enabledProfiles ?? '—'}
          sub={`${c?.profiles ?? 0} total configured`}
          icon={<Workflow className="h-4 w-4" />}
          accent="primary"
        />
        <StatCard
          label="Reports Today"
          value={stats.data?.totals.success ?? c?.successToday ?? '—'}
          sub={`${c?.failedToday ?? 0} failed today`}
          icon={<FileBarChart className="h-4 w-4" />}
          accent="emerald"
        />
        <StatCard
          label="Running Now"
          value={c?.running ?? 0}
          sub={c?.running ? 'pipelines in progress' : 'idle'}
          icon={<Activity className="h-4 w-4" />}
          accent="amber"
          trend={c?.running ? 'up' : 'neutral'}
        />
        <StatCard
          label="Avg Duration"
          value={stats.data?.avgDurationMs ? `${(stats.data.avgDurationMs / 1000).toFixed(1)}s` : '—'}
          sub={`success ${successRate}%`}
          icon={<Clock className="h-4 w-4" />}
          trend={successRate > 90 ? 'up' : 'down'}
        />
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 lg:gap-6">
        {/* Execution timeline */}
        <Card className="xl:col-span-2 p-4 lg:p-5">
          <SectionHeader
            title="Execution Timeline"
            description="Pipeline runs over the last 24 hours"
            icon={<Activity className="h-5 w-5" />}
            action={<Badge variant="secondary" className="gap-1.5"><LiveDot /> live</Badge>}
          />
          {stats.data?.timeline?.length ? (
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={stats.data.timeline} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                <defs>
                  <linearGradient id="gS" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-chart-1)" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="var(--color-chart-1)" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gF" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-chart-3)" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="var(--color-chart-3)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis
                  dataKey="time"
                  tickFormatter={(t) => new Date(t).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                  tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
                  stroke="var(--border)"
                />
                <YAxis tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }} stroke="var(--border)" allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}
                  labelFormatter={(t) => new Date(t).toLocaleString('en-IN')}
                />
                <Area type="monotone" dataKey="success" name="Success" stroke="var(--color-chart-1)" strokeWidth={2} fill="url(#gS)" />
                <Area type="monotone" dataKey="failed" name="Failed" stroke="var(--color-chart-3)" strokeWidth={2} fill="url(#gF)" />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState icon={<Activity className="h-8 w-8" />} title="No executions yet" description="Trigger a profile to see timeline data." />
          )}
        </Card>

        {/* System health */}
        <Card className="p-4 lg:p-5">
          <SectionHeader title="System Health" icon={<Cpu className="h-5 w-5" />} />
          <div className="space-y-4">
            <HealthBar label="CPU Usage" value={health?.cpu ?? 0} unit="%" icon={<Cpu className="h-3.5 w-3.5" />} warn={80} />
            <HealthBar label="Memory" value={health?.memPct ?? 0} unit="%" icon={<Database className="h-3.5 w-3.5" />} warn={85} />
            <div className="grid grid-cols-2 gap-3 pt-2">
              <MiniStat label="Heap" value={`${health?.heapUsedMb ?? 0}MB`} />
              <MiniStat label="Uptime" value={fmtUptime(health?.uptimeSec ?? 0)} />
              <MiniStat label="DB Logs" value={fmtNum(health?.db.logs ?? 0, 0)} />
              <MiniStat label="Failed/hr" value={String(health?.failedLastHour ?? 0)} warn={(health?.failedLastHour ?? 0) > 0} />
            </div>
          </div>
        </Card>
      </div>

      {/* Latest reports + live executions */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 lg:gap-6">
        <Card className="p-4 lg:p-5">
          <SectionHeader
            title="Latest Reports"
            icon={<FileBarChart className="h-5 w-5" />}
            action={<Badge variant="secondary">{reports.data?.length ?? 0}</Badge>}
          />
          <div className="space-y-2 max-h-[360px] overflow-y-auto scroll-thin pr-1">
            {reports.data?.length ? (
              reports.data.map((r) => <ReportRow key={r.id} r={r} />)
            ) : (
              <EmptyState icon={<FileBarChart className="h-8 w-8" />} title="No reports yet" description="Reports appear as profiles run." />
            )}
          </div>
        </Card>

        <Card className="p-4 lg:p-5">
          <SectionHeader
            title="Live Executions"
            icon={<Zap className="h-5 w-5" />}
            action={c?.running ? <Badge className="bg-sky-500/15 text-sky-400 gap-1.5"><LiveDot /> {c.running} active</Badge> : <Badge variant="secondary">idle</Badge>}
          />
          <div className="space-y-2 max-h-[360px] overflow-y-auto scroll-thin pr-1">
            {executions.data?.length ? (
              executions.data.map((e) => <ExecutionRow key={e.id} e={e} />)
            ) : (
              <EmptyState icon={<Zap className="h-8 w-8" />} title="No executions yet" description="Runs will stream here." />
            )}
          </div>
        </Card>
      </div>

      {/* Upcoming runs + trend distribution */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 lg:gap-6">
        <Card className="p-4 lg:p-5">
          <SectionHeader title="Scheduled Next Runs" icon={<Clock className="h-5 w-5" />} />
          <div className="space-y-2">
            {status?.upcoming?.length ? (
              status.upcoming.map((u) => (
                <div key={u.id} className="flex items-center gap-3 rounded-lg border bg-card/40 px-3 py-2.5">
                  <div className="h-8 w-8 rounded-md bg-primary/15 flex items-center justify-center text-primary text-xs font-semibold">
                    {u.symbol.slice(0, 2)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium truncate">{u.name}</div>
                    <div className="text-xs text-muted-foreground">every {u.intervalMin}m</div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-medium tnum">{relTime(u.nextRunAt)}</div>
                    <div className="text-xs text-muted-foreground">{fmtDateTime(u.nextRunAt)}</div>
                  </div>
                </div>
              ))
            ) : (
              <EmptyState title="Nothing scheduled" description="All profiles paused or disabled." />
            )}
          </div>
        </Card>

        <Card className="p-4 lg:p-5">
          <SectionHeader title="Trend Distribution" icon={<Target className="h-5 w-5" />} description="Across recent reports" />
          <TrendDistribution />
        </Card>
      </div>
    </div>
  )
}

function ReportRow({ r }: { r: Report }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border bg-card/40 px-3 py-2.5 hover:border-primary/40 transition-colors">
      <div className="h-9 w-9 rounded-md bg-primary/12 flex items-center justify-center text-primary text-[11px] font-semibold shrink-0">
        {r.symbol.slice(0, 4)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium truncate">{r.symbol}</span>
          <TrendBadge trend={r.trend} score={r.trendScore} />
        </div>
        <div className="text-xs text-muted-foreground tnum">
          Spot {fmtNum(r.spotPrice)} · PCR {fmtNum(r.pcr)} · MaxPain {fmtNum(r.maxPain)}
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="text-xs text-muted-foreground">{relTime(r.generatedAt)}</div>
        <div className="text-[11px] text-muted-foreground/70">{r.expiry}</div>
      </div>
    </div>
  )
}

function ExecutionRow({ e }: { e: Execution }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border bg-card/40 px-3 py-2.5">
      <div className="shrink-0">
        <StatusBadge status={e.status} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium truncate">{e.profile?.symbol ?? ''} <span className="text-muted-foreground font-normal">· {e.profile?.name}</span></div>
        <div className="text-xs text-muted-foreground">
          {e.stage} stage · triggered by {e.triggeredBy}
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="text-xs text-muted-foreground tnum">{e.durationMs ? `${(e.durationMs / 1000).toFixed(1)}s` : '—'}</div>
        <div className="text-[11px] text-muted-foreground/70">{relTime(e.startedAt)}</div>
      </div>
    </div>
  )
}

function HealthBar({ label, value, unit, icon, warn }: { label: string; value: number; unit: string; icon: React.ReactNode; warn?: number }) {
  const v = Math.round(value)
  const isWarn = warn ? v > warn : false
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs font-medium flex items-center gap-1.5 text-muted-foreground">{icon} {label}</span>
        <span className={`text-xs font-semibold tnum ${isWarn ? 'text-amber-500' : ''}`}>{v}{unit}</span>
      </div>
      <Progress value={v} className={`h-1.5 ${isWarn ? '[&>div]:bg-amber-500' : ''}`} />
    </div>
  )
}

function MiniStat({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="rounded-lg border bg-muted/30 px-3 py-2">
      <div className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</div>
      <div className={`text-sm font-semibold tnum ${warn ? 'text-amber-500' : ''}`}>{value}</div>
    </div>
  )
}

function Donut({ value, label }: { value: number; label: string }) {
  const v = Math.max(0, Math.min(100, value))
  const r = 28
  const circ = 2 * Math.PI * r
  const offset = circ - (v / 100) * circ
  const color = v > 90 ? 'var(--color-chart-1)' : v > 70 ? 'var(--color-chart-2)' : 'var(--color-chart-3)'
  return (
    <div className="relative h-16 w-16">
      <svg className="h-16 w-16 -rotate-90" viewBox="0 0 64 64">
        <circle cx="32" cy="32" r={r} fill="none" stroke="var(--muted)" strokeWidth="6" />
        <circle cx="32" cy="32" r={r} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={offset} className="transition-all duration-700" />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-sm font-bold tnum">{v}%</span>
      </div>
      <span className="sr-only">{label}</span>
    </div>
  )
}

function TrendDistribution() {
  const { data } = useQuery({
    queryKey: ['reports-trend-dist'],
    queryFn: () => api<Report[]>('/api/reports?limit=200'),
    refetchInterval: 20000,
  })
  const counts = { bullish: 0, bearish: 0, neutral: 0 }
  for (const r of data ?? []) counts[r.trend as keyof typeof counts] = (counts[r.trend as keyof typeof counts] ?? 0) + 1
  const total = counts.bullish + counts.bearish + counts.neutral || 1
  const chartData = [
    { name: 'Bullish', value: counts.bullish, color: 'var(--color-chart-1)' },
    { name: 'Neutral', value: counts.neutral, color: 'var(--color-chart-2)' },
    { name: 'Bearish', value: counts.bearish, color: 'var(--color-chart-3)' },
  ]
  return (
    <div className="space-y-3">
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={chartData} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} stroke="var(--border)" />
          <YAxis tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }} stroke="var(--border)" allowDecimals={false} />
          <Tooltip contentStyle={{ background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} />
          <Bar dataKey="value" radius={[6, 6, 0, 0]}>
            {chartData.map((d, i) => <Cell key={i} fill={d.color} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="grid grid-cols-3 gap-2">
        {chartData.map((d) => (
          <div key={d.name} className="rounded-lg border bg-card/40 px-3 py-2">
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className="h-2 w-2 rounded-full" style={{ background: d.color }} /> {d.name}
            </div>
            <div className="text-lg font-semibold tnum">{d.value}</div>
            <div className="text-[10px] text-muted-foreground tnum">{Math.round((d.value / total) * 100)}%</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function fmtUptime(s: number): string {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function MiniPill({ label, value, tone }: { label: string; value: string; tone: 'emerald' | 'rose' | 'amber' | 'sky' | 'muted' }) {
  const map: Record<string, string> = {
    emerald: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
    rose: 'bg-rose-500/10 text-rose-500 border-rose-500/20',
    amber: 'bg-amber-500/10 text-amber-500 border-amber-500/20',
    sky: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
    muted: 'bg-muted/50 text-muted-foreground border-border',
  }
  return (
    <div className={cn('inline-flex items-center gap-1.5 rounded-md border px-2 py-1', map[tone])}>
      <span className="text-[10px] uppercase tracking-wide opacity-80">{label}</span>
      <span className="text-xs font-semibold tnum">{value}</span>
    </div>
  )
}

function HeroSparkline() {
  const { data } = useQuery({
    queryKey: ['history-all-mini'],
    queryFn: () => api<{ points: { symbol: string; generatedAt: string; spotPrice: number; pcr: number }[] }>('/api/analytics/history?limit=60'),
    refetchInterval: 20000,
  })
  const points = data?.points ?? []
  if (points.length < 3) {
    return (
      <div className="flex flex-col items-center justify-center w-28 h-16 rounded-lg border border-dashed text-[10px] text-muted-foreground/60">
        <TrendingUp className="h-4 w-4 mb-1 opacity-40" /> warming up
      </div>
    )
  }
  // Build a single normalized series of avg spot per timestamp
  const byTime: Record<string, { sum: number; n: number }> = {}
  for (const p of points) {
    const k = new Date(p.generatedAt).getTime()
    if (!byTime[k]) byTime[k] = { sum: 0, n: 0 }
    byTime[k].sum += p.pcr
    byTime[k].n++
  }
  const series = Object.entries(byTime)
    .map(([k, v]) => ({ t: Number(k), v: v.sum / v.n }))
    .sort((a, b) => a.t - b.t)
    .slice(-20)
  const vals = series.map((s) => s.v)
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const range = max - min || 1
  const w = 110
  const h = 50
  const path = series
    .map((s, i) => {
      const x = (i / (series.length - 1)) * w
      const y = h - ((s.v - min) / range) * h
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  const lastVal = vals[vals.length - 1]
  const firstVal = vals[0]
  const up = lastVal >= firstVal
  const color = up ? 'var(--color-chart-1)' : 'var(--color-chart-3)'
  return (
    <div className="flex flex-col items-center">
      <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">Avg PCR</div>
      <svg width={w} height={h} className="overflow-visible">
        <defs>
          <linearGradient id="sparkG" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <path d={`${path} L${w},${h} L0,${h} Z`} fill="url(#sparkG)" />
        <path d={path} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="text-[11px] font-semibold tnum" style={{ color }}>{lastVal.toFixed(2)}</div>
    </div>
  )
}
