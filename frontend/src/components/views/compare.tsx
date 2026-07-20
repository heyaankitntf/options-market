'use client'

import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  GitCompareArrows, X, ArrowUp, ArrowDown, Minus, Clock, TrendingUp, TrendingDown,
} from 'lucide-react'
import {
  Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid, ReferenceLine,
} from 'recharts'
import { api, type CompareRow } from '@/lib/api'
import { fmtNum, fmtOI, fmtSigned, fmtDateTime, relTime } from '@/lib/format'
import { SectionHeader, TrendBadge, EmptyState } from '@/components/ui/primitives'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'

interface CompareResponse {
  reports: CompareRow[]
  deltas: Array<{
    from: string
    to: string
    spotDelta: number
    spotDeltaPct: number
    pcrDelta: number
    maxPainDelta: number
    callOiDelta: number
    putOiDelta: number
    ivCallDelta: number
    ivPutDelta: number
    trendScoreDelta: number
    trendChanged: boolean
    timeDeltaMin: number
  }>
}

export function CompareSheet({
  ids,
  onClose,
}: {
  ids: string[]
  onClose: () => void
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['compare', ids.join(',')],
    queryFn: () => api<CompareResponse>(`/api/reports/compare?ids=${ids.join(',')}`),
    enabled: ids.length >= 2,
  })

  const reports = data?.reports ?? []
  const deltas = data?.deltas ?? []

  return (
    <Sheet open={ids.length >= 2} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-3xl lg:max-w-4xl p-0 flex flex-col">
        <SheetHeader className="px-5 py-4 border-b">
          <div className="flex items-center justify-between">
            <div>
              <SheetTitle className="flex items-center gap-2">
                <GitCompareArrows className="h-5 w-5 text-primary" />
                Report Comparison
                <Badge variant="secondary">{reports.length} snapshots</Badge>
              </SheetTitle>
              <p className="text-xs text-muted-foreground mt-0.5">
                {reports[0]?.symbol ?? ''} · {reports.length >= 2 ? `${fmtDateTime(reports[0].generatedAt)} → ${fmtDateTime(reports[reports.length - 1].generatedAt)}` : ''}
              </p>
            </div>
            <Button size="icon" variant="ghost" onClick={onClose}><X className="h-4 w-4" /></Button>
          </div>
        </SheetHeader>
        <ScrollArea className="flex-1">
          <div className="p-5 space-y-5">
            {isLoading ? (
              <div className="space-y-3">
                {[1, 2, 3].map((i) => <div key={i} className="h-16 rounded-lg bg-muted/40 animate-pulse" />)}
              </div>
            ) : reports.length < 2 ? (
              <EmptyState icon={<GitCompareArrows className="h-8 w-8" />} title="Select 2+ reports to compare" />
            ) : (
              <>
                {/* Spot evolution chart */}
                <Card className="p-4">
                  <div className="text-sm font-semibold mb-3 flex items-center gap-2">
                    <TrendingUp className="h-4 w-4 text-primary" /> Spot &amp; Indicator Evolution
                  </div>
                  <ResponsiveContainer width="100%" height={200}>
                    <LineChart data={reports} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                      <XAxis
                        dataKey="generatedAt"
                        tickFormatter={(t) => new Date(t).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                        tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
                        stroke="var(--border)"
                      />
                      <YAxis yAxisId="l" tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }} stroke="var(--border)" />
                      <YAxis yAxisId="r" orientation="right" domain={[0, 2]} tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }} stroke="var(--border)" />
                      <Tooltip contentStyle={{ background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} labelFormatter={(t) => fmtDateTime(t)} />
                      <Line yAxisId="l" type="monotone" dataKey="spotPrice" name="Spot" stroke="var(--color-chart-1)" strokeWidth={2} dot={{ r: 3 }} />
                      <Line yAxisId="l" type="monotone" dataKey="maxPain" name="Max Pain" stroke="var(--color-chart-2)" strokeWidth={2} strokeDasharray="5 4" dot={false} />
                      <Line yAxisId="r" type="monotone" dataKey="pcr" name="PCR" stroke="var(--color-chart-4)" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </Card>

                {/* Delta cards between consecutive snapshots */}
                <div>
                  <div className="text-sm font-semibold mb-3 flex items-center gap-2">
                    <ArrowUp className="h-4 w-4 text-primary" /> Changes Between Snapshots
                  </div>
                  <div className="space-y-2">
                    {deltas.map((d, i) => {
                      const from = reports[i]
                      const to = reports[i + 1]
                      if (!from || !to) return null
                      return (
                        <div key={i} className="rounded-lg border bg-card/40 p-3">
                          <div className="flex items-center justify-between mb-2.5">
                            <div className="flex items-center gap-2 text-xs text-muted-foreground">
                              <Clock className="h-3 w-3" />
                              {new Date(from.generatedAt).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                              <ArrowUp className="h-3 w-3 rotate-90" />
                              {new Date(to.generatedAt).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                              <Badge variant="outline" className="text-[10px]">{d.timeDeltaMin}m apart</Badge>
                            </div>
                            {d.trendChanged && (
                              <Badge className="bg-amber-500/15 text-amber-500 text-[10px] gap-1">
                                <TrendingDown className="h-3 w-3" /> Trend shift
                              </Badge>
                            )}
                          </div>
                          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
                            <DeltaTile label="Spot" value={d.spotDelta} suffix="" pct={d.spotDeltaPct} />
                            <DeltaTile label="PCR" value={d.pcrDelta} suffix="" decimals={2} />
                            <DeltaTile label="Max Pain" value={d.maxPainDelta} suffix="" />
                            <DeltaTile label="Call OI" value={d.callOiDelta} suffix="" compact />
                            <DeltaTile label="Put OI" value={d.putOiDelta} suffix="" compact />
                            <DeltaTile label="IV Call" value={d.ivCallDelta} suffix="%" decimals={2} />
                            <DeltaTile label="Trend Score" value={d.trendScoreDelta} suffix="" />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>

                {/* Side-by-side comparison table */}
                <div>
                  <div className="text-sm font-semibold mb-3">Indicator Side-by-Side</div>
                  <div className="rounded-lg border overflow-hidden overflow-x-auto scroll-thin">
                    <table className="w-full text-xs">
                      <thead className="bg-muted/40">
                        <tr className="text-muted-foreground">
                          <th className="px-3 py-2 text-left font-medium">Indicator</th>
                          {reports.map((r, i) => (
                            <th key={r.id} className="px-3 py-2 text-right font-medium">
                              <div className="text-[10px] text-muted-foreground/70">#{i + 1}</div>
                              <div className="text-foreground text-[10px] font-normal">{new Date(r.generatedAt).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</div>
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        <CompareRow2 label="Spot Price" reports={reports} field="spotPrice" fmt={(v) => fmtNum(v)} />
                        <CompareRow2 label="ATM Strike" reports={reports} field="atmStrike" fmt={(v) => fmtNum(v, 0)} />
                        <CompareRow2 label="PCR (OI)" reports={reports} field="pcr" fmt={(v) => fmtNum(v)} highlight />
                        <CompareRow2 label="Max Pain" reports={reports} field="maxPain" fmt={(v) => fmtNum(v)} />
                        <CompareRow2 label="IV Call" reports={reports} field="ivCall" fmt={(v) => v + '%'} />
                        <CompareRow2 label="IV Put" reports={reports} field="ivPut" fmt={(v) => v + '%'} />
                        <CompareRow2 label="Total Call OI" reports={reports} field="totalCallOi" fmt={(v) => fmtOI(v)} />
                        <CompareRow2 label="Total Put OI" reports={reports} field="totalPutOi" fmt={(v) => fmtOI(v)} />
                        <CompareRow2 label="Support" reports={reports} field="support" fmt={(v) => fmtNum(v)} />
                        <CompareRow2 label="Resistance" reports={reports} field="resistance" fmt={(v) => fmtNum(v)} />
                        <tr className="border-t bg-muted/20">
                          <td className="px-3 py-2 font-medium">Trend</td>
                          {reports.map((r) => (
                            <td key={r.id} className="px-3 py-2 text-right">
                              <TrendBadge trend={r.trend} score={r.trendScore} />
                            </td>
                          ))}
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  )
}

function DeltaTile({
  label, value, suffix, pct, decimals = 0, compact,
}: {
  label: string
  value: number
  suffix: string
  pct?: number
  decimals?: number
  compact?: boolean
}) {
  const up = value > 0
  const down = value < 0
  const color = up ? 'text-emerald-500' : down ? 'text-rose-500' : 'text-muted-foreground'
  const bg = up ? 'bg-emerald-500/8' : down ? 'bg-rose-500/8' : 'bg-muted/30'
  const fmt = compact ? fmtOI : (v: number) => fmtNum(v, decimals)
  return (
    <div className={cn('rounded-md px-2.5 py-1.5', bg)}>
      <div className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</div>
      <div className={cn('text-sm font-semibold tnum flex items-center gap-1', color)}>
        {up ? <ArrowUp className="h-3 w-3" /> : down ? <ArrowDown className="h-3 w-3" /> : <Minus className="h-3 w-3 opacity-40" />}
        {fmtSigned(value, decimals)}{suffix}
      </div>
      {pct != null && (
        <div className={cn('text-[10px] tnum', color)}>{fmtSigned(pct)}%</div>
      )}
    </div>
  )
}

function CompareRow2({
  label, reports, field, fmt, highlight,
}: {
  label: string
  reports: CompareRow[]
  field: keyof CompareRow
  fmt: (v: number) => string
  highlight?: boolean
}) {
  const values = reports.map((r) => r[field] as number)
  const min = Math.min(...values)
  const max = Math.max(...values)
  return (
    <tr className="border-b last:border-0 hover:bg-muted/20">
      <td className={cn('px-3 py-2 font-medium', highlight && 'text-primary')}>{label}</td>
      {reports.map((r) => {
        const v = r[field] as number
        const isMax = v === max && max !== min
        const isMin = v === min && max !== min
        return (
          <td key={r.id} className={cn('px-3 py-2 text-right tnum', isMax && 'text-emerald-500', isMin && 'text-rose-500')}>
            {fmt(v)}
          </td>
        )
      })}
    </tr>
  )
}
