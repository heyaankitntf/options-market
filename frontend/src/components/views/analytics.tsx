'use client'

import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid,
  Line, LineChart, BarChart, Bar, Cell, ReferenceLine, ComposedChart,
} from 'recharts'
import {
  LineChart as LineIcon, Activity, Target, Flame, TrendingUp, TrendingDown,
  Gauge, BarChart3, Zap, ArrowUpDown,
} from 'lucide-react'
import { api, type HistoryResponse, type SymbolAnalytics } from '@/lib/api'
import { SYMBOL_SPECS } from '@/lib/symbols'
import { fmtNum, fmtOI, fmtSigned, relTime, fmtDateTime } from '@/lib/format'
import { SectionHeader, TrendBadge, EmptyState, StatCard } from '@/components/ui/primitives'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'

export function AnalyticsView() {
  const [symbol, setSymbol] = React.useState('NIFTY')

  const history = useQuery({
    queryKey: ['history', symbol],
    queryFn: () => api<HistoryResponse>(`/api/analytics/history?symbol=${symbol}&limit=100`),
    refetchInterval: 20000,
  })
  const detail = useQuery({
    queryKey: ['symbol-analytics', symbol],
    queryFn: () => api<SymbolAnalytics>(`/api/analytics/symbol?symbol=${symbol}`),
    refetchInterval: 20000,
  })

  const points = history.data?.points ?? []
  const agg = detail.data?.aggregates
  const latest = detail.data?.latest

  return (
    <div className="space-y-4">
      {/* Header */}
      <Card className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="h-11 w-11 rounded-xl bg-gradient-to-br from-primary/20 to-primary/5 border border-primary/20 flex items-center justify-center">
            <LineIcon className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h2 className="font-semibold text-base">Deep Analytics</h2>
            <p className="text-xs text-muted-foreground">Historical trends &amp; option structure for {SYMBOL_SPECS.find((s) => s.symbol === symbol)?.label}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Select value={symbol} onValueChange={setSymbol}>
            <SelectTrigger className="w-[180px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              {SYMBOL_SPECS.map((s) => <SelectItem key={s.symbol} value={s.symbol}>{s.symbol} — {s.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </Card>

      {/* Aggregates */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-4">
        <StatCard
          label="Avg Spot"
          value={agg ? fmtNum(agg.avgSpot) : '—'}
          sub={agg ? `${fmtSigned(agg.spotChange, 0)} (${fmtSigned(agg.spotChangePct)}%) over ${agg.sampleCount} runs` : 'loading'}
          icon={<Activity className="h-4 w-4" />}
          accent="primary"
          trend={agg ? (agg.spotChange >= 0 ? 'up' : 'down') : 'neutral'}
        />
        <StatCard
          label="Avg PCR"
          value={agg ? fmtNum(agg.avgPcr) : '—'}
          sub={agg ? `slope ${fmtSigned(agg.pcrSlope)} / run` : ''}
          icon={<Gauge className="h-4 w-4" />}
          accent={agg ? (agg.avgPcr > 1.1 ? 'emerald' : agg.avgPcr < 0.9 ? 'rose' : 'default') : 'default'}
        />
        <StatCard
          label="Avg Max Pain"
          value={agg ? fmtNum(agg.avgMaxPain) : '—'}
          sub={latest ? `latest ${fmtNum(latest.maxPain)}` : ''}
          icon={<Target className="h-4 w-4" />}
          accent="amber"
        />
        <StatCard
          label="Spot Range"
          value={agg ? `${fmtNum(agg.spotRange[0])}` : '—'}
          sub={agg ? `to ${fmtNum(agg.spotRange[1])}` : ''}
          icon={<ArrowUpDown className="h-4 w-4" />}
        />
      </div>

      {/* Spot vs Max Pain chart */}
      <Card className="p-4 lg:p-5">
        <SectionHeader
          title="Spot vs Max Pain"
          description="Price magnetism over recent snapshots"
          icon={<TrendingUp className="h-5 w-5" />}
          action={
            latest && (
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-primary" /> Spot
                </Badge>
                <Badge variant="outline" className="gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-amber-500" /> Max Pain
                </Badge>
              </div>
            )
          }
        />
        {points.length < 2 ? (
          <EmptyState icon={<TrendingUp className="h-8 w-8" />} title="Insufficient data" description="Need at least 2 snapshots for trends." />
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={points} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
              <defs>
                <linearGradient id="spotGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--color-chart-1)" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="var(--color-chart-1)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="generatedAt"
                tickFormatter={(t) => new Date(t).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
                stroke="var(--border)"
              />
              <YAxis
                yAxisId="left"
                tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
                stroke="var(--border)"
                domain={['auto', 'auto']}
              />
              <Tooltip
                contentStyle={{ background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}
                labelFormatter={(t) => fmtDateTime(t)}
              />
              <Area yAxisId="left" type="monotone" dataKey="spotPrice" name="Spot" stroke="var(--color-chart-1)" strokeWidth={2} fill="url(#spotGrad)" />
              <Line yAxisId="left" type="monotone" dataKey="maxPain" name="Max Pain" stroke="var(--color-chart-2)" strokeWidth={2} strokeDasharray="5 4" dot={false} />
              <Line yAxisId="left" type="monotone" dataKey="support" name="Support" stroke="var(--color-chart-1)" strokeWidth={1} strokeOpacity={0.4} dot={false} />
              <Line yAxisId="left" type="monotone" dataKey="resistance" name="Resistance" stroke="var(--color-chart-3)" strokeWidth={1} strokeOpacity={0.4} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </Card>

      {/* Two-column: PCR + OI buildup */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 lg:gap-6">
        <Card className="p-4 lg:p-5">
          <SectionHeader
            title="PCR Evolution"
            description="Put-Call ratio with bullish/bearish bands"
            icon={<Gauge className="h-5 w-5" />}
          />
          {points.length < 2 ? (
            <EmptyState icon={<Gauge className="h-8 w-8" />} title="Waiting for data" />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={points} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                <defs>
                  <linearGradient id="pcrGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-chart-4)" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="var(--color-chart-4)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis
                  dataKey="generatedAt"
                  tickFormatter={(t) => new Date(t).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                  tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
                  stroke="var(--border)"
                />
                <YAxis tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }} stroke="var(--border)" domain={[0.5, 1.5]} />
                <Tooltip contentStyle={{ background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} labelFormatter={(t) => fmtDateTime(t)} />
                <ReferenceLine y={1.1} stroke="var(--color-chart-1)" strokeDasharray="4 4" strokeOpacity={0.5} label={{ value: 'bull 1.1', fontSize: 9, fill: 'var(--color-chart-1)', position: 'right' }} />
                <ReferenceLine y={0.9} stroke="var(--color-chart-3)" strokeDasharray="4 4" strokeOpacity={0.5} label={{ value: 'bear 0.9', fontSize: 9, fill: 'var(--color-chart-3)', position: 'right' }} />
                <Area type="monotone" dataKey="pcr" name="PCR (OI)" stroke="var(--color-chart-4)" strokeWidth={2} fill="url(#pcrGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card className="p-4 lg:p-5">
          <SectionHeader
            title="OI Buildup"
            description="Call vs Put open interest trend"
            icon={<BarChart3 className="h-5 w-5" />}
          />
          {points.length < 2 ? (
            <EmptyState icon={<BarChart3 className="h-8 w-8" />} title="Waiting for data" />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart data={points} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis
                  dataKey="generatedAt"
                  tickFormatter={(t) => new Date(t).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                  tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
                  stroke="var(--border)"
                />
                <YAxis tickFormatter={(v) => fmtOI(v)} tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }} stroke="var(--border)" />
                <Tooltip
                  contentStyle={{ background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}
                  labelFormatter={(t) => fmtDateTime(t)}
                  formatter={(v: number) => fmtOI(v)}
                />
                <Bar dataKey="totalCallOi" name="Call OI" fill="var(--color-chart-3)" fillOpacity={0.6} radius={[2, 2, 0, 0]} />
                <Bar dataKey="totalPutOi" name="Put OI" fill="var(--color-chart-1)" fillOpacity={0.6} radius={[2, 2, 0, 0]} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      {/* IV Smile + Trend distribution */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 lg:gap-6">
        <Card className="p-4 lg:p-5">
          <SectionHeader
            title="IV Outlook"
            description="ATM Call vs Put implied volatility"
            icon={<Flame className="h-5 w-5" />}
          />
          {points.length < 2 ? (
            <EmptyState icon={<Flame className="h-8 w-8" />} title="Waiting for data" />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={points} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                  <XAxis
                    dataKey="generatedAt"
                    tickFormatter={(t) => new Date(t).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                    tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
                    stroke="var(--border)"
                  />
                  <YAxis tickFormatter={(v) => v + '%'} tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }} stroke="var(--border)" />
                  <Tooltip contentStyle={{ background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} labelFormatter={(t) => fmtDateTime(t)} formatter={(v: number) => v + '%'} />
                  <Line type="monotone" dataKey="ivCall" name="IV Call" stroke="var(--color-chart-1)" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="ivPut" name="IV Put" stroke="var(--color-chart-3)" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
              {agg && (
                <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t">
                  <div className="text-xs">
                    <span className="text-muted-foreground">IV Call range</span>
                    <span className="ml-2 font-medium tnum">{fmtNum(agg.ivCallRange[0], 1)}% – {fmtNum(agg.ivCallRange[1], 1)}%</span>
                  </div>
                  <div className="text-xs">
                    <span className="text-muted-foreground">IV Put range</span>
                    <span className="ml-2 font-medium tnum">{fmtNum(agg.ivPutRange[0], 1)}% – {fmtNum(agg.ivPutRange[1], 1)}%</span>
                  </div>
                </div>
              )}
            </>
          )}
        </Card>

        <Card className="p-4 lg:p-5">
          <SectionHeader
            title="Trend Distribution"
            description={`${agg?.sampleCount ?? 0} recent snapshots`}
            icon={<Zap className="h-5 w-5" />}
          />
          {agg ? (
            <div className="space-y-4">
              <div className="flex items-center gap-2 h-4 rounded-full overflow-hidden">
                <div className="h-full bg-emerald-500/70 transition-all" style={{ width: `${(agg.trendDist.bullish / agg.sampleCount) * 100}%` }} />
                <div className="h-full bg-amber-500/70 transition-all" style={{ width: `${(agg.trendDist.neutral / agg.sampleCount) * 100}%` }} />
                <div className="h-full bg-rose-500/70 transition-all" style={{ width: `${(agg.trendDist.bearish / agg.sampleCount) * 100}%` }} />
              </div>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: 'Bullish', count: agg.trendDist.bullish, color: 'bg-emerald-500', text: 'text-emerald-500' },
                  { label: 'Neutral', count: agg.trendDist.neutral, color: 'bg-amber-500', text: 'text-amber-500' },
                  { label: 'Bearish', count: agg.trendDist.bearish, color: 'bg-rose-500', text: 'text-rose-500' },
                ].map((t) => (
                  <div key={t.label} className="rounded-lg border bg-card/40 p-3 text-center">
                    <div className={cn('h-2 w-2 rounded-full mx-auto mb-2', t.color)} />
                    <div className={cn('text-2xl font-bold tnum', t.text)}>{t.count}</div>
                    <div className="text-[11px] text-muted-foreground">{t.label}</div>
                    <div className="text-[10px] text-muted-foreground tnum mt-0.5">{Math.round((t.count / agg.sampleCount) * 100)}%</div>
                  </div>
                ))}
              </div>
              {latest && (
                <div className="rounded-lg border bg-muted/20 p-3 flex items-center justify-between">
                  <div>
                    <div className="text-xs text-muted-foreground">Latest snapshot</div>
                    <div className="text-sm font-medium">{relTime(latest.generatedAt)}</div>
                  </div>
                  <TrendBadge trend={latest.trend} score={latest.trendScore} />
                </div>
              )}
            </div>
          ) : (
            <EmptyState icon={<Zap className="h-8 w-8" />} title="Loading" />
          )}
        </Card>
      </div>
    </div>
  )
}
