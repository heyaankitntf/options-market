'use client'

import * as React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  FileBarChart, Search, Download, GitCompareArrows, X, Filter,
  TrendingUp, TrendingDown, ArrowUpDown, ArrowRight, FileJson, FileSpreadsheet, FileType,
} from 'lucide-react'
import { api, type Report, type ReportDetail } from '@/lib/api'
import { fmtNum, fmtOI, fmtDateTime, relTime, fmtSigned } from '@/lib/format'
import { SectionHeader, TrendBadge, EmptyState, StatusBadge } from '@/components/ui/primitives'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Checkbox } from '@/components/ui/checkbox'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'
import { CompareSheet } from '@/components/views/compare'

const SYMBOLS = ['ALL', 'NIFTY', 'BANKNIFTY', 'SENSEX', 'FINNIFTY', 'MIDCPNIFTY']
const TRENDS = ['ALL', 'bullish', 'bearish', 'neutral']

export function ReportsView() {
  const qc = useQueryClient()
  const { toast } = useToast()
  const [symbol, setSymbol] = React.useState('ALL')
  const [trend, setTrend] = React.useState('ALL')
  const [q, setQ] = React.useState('')
  const [selected, setSelected] = React.useState<Report | null>(null)
  const [compareIds, setCompareIds] = React.useState<string[]>([])
  const [compareOpen, setCompareOpen] = React.useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['reports', symbol, trend],
    queryFn: () => {
      const params = new URLSearchParams({ limit: '150' })
      if (symbol !== 'ALL') params.set('symbol', symbol)
      if (trend !== 'ALL') params.set('trend', trend)
      return api<Report[]>(`/api/reports?${params}`)
    },
    refetchInterval: 12000,
  })

  const filtered = React.useMemo(() => {
    if (!data) return []
    if (!q) return data
    const ql = q.toLowerCase()
    return data.filter((r) => r.symbol.toLowerCase().includes(ql) || r.expiry.includes(q) || String(r.spotPrice).includes(q))
  }, [data, q])

  const toggleCompare = (id: string) => {
    setCompareIds((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length < 4 ? [...p, id] : p))
  }

  const doExport = async (reportId: string, format: 'csv' | 'json' | 'xlsx' | 'pdf') => {
    try {
      if (format === 'pdf') {
        const res = await fetch(`/api/reports/${reportId}/export?format=pdf`)
        const html = await res.text()
        const w = window.open('', '_blank')
        if (w) { w.document.write(html); w.document.close() }
        return
      }
      window.location.href = `/api/reports/${reportId}/export?format=${format}`
      toast({ title: `Exporting ${format.toUpperCase()}` })
    } catch (e) {
      toast({ title: 'Export failed', description: String(e), variant: 'destructive' })
    }
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-col lg:flex-row gap-3 lg:items-center">
          <div className="flex items-center gap-2 flex-1">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input placeholder="Search symbol, expiry, spot..." value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" />
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Select value={symbol} onValueChange={setSymbol}>
              <SelectTrigger className="w-[140px]"><SelectValue /></SelectTrigger>
              <SelectContent>{SYMBOLS.map((s) => <SelectItem key={s} value={s}>{s === 'ALL' ? 'All Symbols' : s}</SelectItem>)}</SelectContent>
            </Select>
            <Select value={trend} onValueChange={setTrend}>
              <SelectTrigger className="w-[140px]"><SelectValue /></SelectTrigger>
              <SelectContent>{TRENDS.map((t) => <SelectItem key={t} value={t} className="capitalize">{t === 'ALL' ? 'All Trends' : t}</SelectItem>)}</SelectContent>
            </Select>
            {compareIds.length >= 2 && (
              <Button size="sm" className="gap-1.5" onClick={() => setCompareOpen(true)}>
                <GitCompareArrows className="h-4 w-4" /> Compare ({compareIds.length})
              </Button>
            )}
            {compareIds.length > 0 && (
              <Button size="sm" variant="ghost" onClick={() => setCompareIds([])}>Clear</Button>
            )}
          </div>
        </div>
      </Card>

      <Card className="p-0 overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-medium">
            <FileBarChart className="h-4 w-4 text-primary" />
            Reports <Badge variant="secondary" className="ml-1">{filtered.length}</Badge>
          </div>
          {compareIds.length > 0 && (
            <span className="text-xs text-muted-foreground">Select up to 4 to compare</span>
          )}
        </div>
        <div className="overflow-x-auto scroll-thin">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/30 text-xs text-muted-foreground">
                <th className="w-10 px-3 py-2.5 text-left"><Checkbox checked={false} /></th>
                <th className="px-3 py-2.5 text-left font-medium">Symbol</th>
                <th className="px-3 py-2.5 text-right font-medium">Spot</th>
                <th className="px-3 py-2.5 text-right font-medium">PCR</th>
                <th className="px-3 py-2.5 text-right font-medium">Max Pain</th>
                <th className="px-3 py-2.5 text-right font-medium">ATM</th>
                <th className="px-3 py-2.5 text-right font-medium">Total OI (C/P)</th>
                <th className="px-3 py-2.5 text-center font-medium">Trend</th>
                <th className="px-3 py-2.5 text-left font-medium">Expiry</th>
                <th className="px-3 py-2.5 text-right font-medium">Generated</th>
                <th className="px-3 py-2.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={11} className="px-3 py-8 text-center text-muted-foreground">Loading…</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={11} className="px-3 py-8"><EmptyState icon={<FileBarChart className="h-8 w-8" />} title="No reports found" description="Adjust filters or wait for profiles to generate reports." /></td></tr>
              ) : (
                filtered.map((r) => (
                  <tr key={r.id} className="border-b last:border-0 hover:bg-muted/30 transition-colors group">
                    <td className="px-3 py-2.5">
                      <Checkbox checked={compareIds.includes(r.id)} onCheckedChange={() => toggleCompare(r.id)} />
                    </td>
                    <td className="px-3 py-2.5">
                      <button className="font-medium text-left hover:text-primary" onClick={() => setSelected(r)}>
                        {r.symbol}
                      </button>
                      <div className="text-[11px] text-muted-foreground">{r.profile?.name}</div>
                    </td>
                    <td className="px-3 py-2.5 text-right tnum font-medium">{fmtNum(r.spotPrice)}</td>
                    <td className="px-3 py-2.5 text-right tnum">
                      <span className={r.pcr > 1.1 ? 'text-emerald-500' : r.pcr < 0.9 ? 'text-rose-500' : ''}>{fmtNum(r.pcr)}</span>
                    </td>
                    <td className="px-3 py-2.5 text-right tnum text-muted-foreground">{fmtNum(r.maxPain)}</td>
                    <td className="px-3 py-2.5 text-right tnum text-muted-foreground">{fmtNum(r.atmStrike, 0)}</td>
                    <td className="px-3 py-2.5 text-right tnum text-xs text-muted-foreground">
                      {fmtOI(r.totalCallOi)} / {fmtOI(r.totalPutOi)}
                    </td>
                    <td className="px-3 py-2.5 text-center"><TrendBadge trend={r.trend} score={r.trendScore} /></td>
                    <td className="px-3 py-2.5 text-muted-foreground text-xs">{r.expiry}</td>
                    <td className="px-3 py-2.5 text-right text-xs text-muted-foreground">{relTime(r.generatedAt)}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <TooltipProvider delayDuration={200}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => setSelected(r)}>
                                <ArrowRight className="h-3.5 w-3.5" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>Open detail</TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                        <ExportMenu onExport={(f) => doExport(r.id, f)} />
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <ReportDetailSheet report={selected} onClose={() => setSelected(null)} />
      <CompareSheet ids={compareOpen ? compareIds : []} onClose={() => setCompareOpen(false)} />
    </div>
  )
}

function ExportMenu({ onExport }: { onExport: (f: 'csv' | 'json' | 'xlsx' | 'pdf') => void }) {
  return (
    <div className="flex items-center gap-0.5">
      <TooltipProvider delayDuration={200}>
        <Tooltip><TooltipTrigger asChild><Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => onExport('csv')}><FileSpreadsheet className="h-3.5 w-3.5" /></Button></TooltipTrigger><TooltipContent>Export CSV</TooltipContent></Tooltip>
        <Tooltip><TooltipTrigger asChild><Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => onExport('json')}><FileJson className="h-3.5 w-3.5" /></Button></TooltipTrigger><TooltipContent>Export JSON</TooltipContent></Tooltip>
        <Tooltip><TooltipTrigger asChild><Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => onExport('xlsx')}><FileSpreadsheet className="h-3.5 w-3.5" /></Button></TooltipTrigger><TooltipContent>Export Excel</TooltipContent></Tooltip>
        <Tooltip><TooltipTrigger asChild><Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => onExport('pdf')}><FileType className="h-3.5 w-3.5" /></Button></TooltipTrigger><TooltipContent>Print / PDF</TooltipContent></Tooltip>
      </TooltipProvider>
    </div>
  )
}

function ReportDetailSheet({ report, onClose }: { report: Report | null; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ['report', report?.id],
    queryFn: () => api<ReportDetail>(`/api/reports/${report!.id}`),
    enabled: !!report,
  })

  return (
    <Sheet open={!!report} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-2xl lg:max-w-3xl p-0 flex flex-col">
        <SheetHeader className="px-5 py-4 border-b">
          <div className="flex items-center justify-between">
            <div>
              <SheetTitle className="flex items-center gap-2">
                {report?.symbol} <span className="text-muted-foreground font-normal text-sm">· Options Chain Report</span>
              </SheetTitle>
              <p className="text-xs text-muted-foreground mt-0.5">
                {report && fmtDateTime(report.generatedAt)} · Expiry {report?.expiry}
              </p>
            </div>
            <Button size="icon" variant="ghost" onClick={onClose}><X className="h-4 w-4" /></Button>
          </div>
        </SheetHeader>
        {report && (
          <ScrollArea className="flex-1">
            <div className="p-5 space-y-5">
              {/* Key indicators */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                <IndTile label="Spot" value={fmtNum(report.spotPrice)} />
                <IndTile label="ATM" value={fmtNum(report.atmStrike, 0)} />
                <IndTile label="PCR (OI)" value={fmtNum(report.pcr)} accent={report.pcr > 1.1 ? 'emerald' : report.pcr < 0.9 ? 'rose' : 'default'} />
                <IndTile label="PCR (Vol)" value={fmtNum(report.pcrVolume)} />
                <IndTile label="Max Pain" value={fmtNum(report.maxPain)} />
                <IndTile label="IV Call" value={`${fmtNum(report.ivCall)}%`} />
                <IndTile label="IV Put" value={`${fmtNum(report.ivPut)}%`} />
                <IndTile label="IV Skew" value={fmtSigned(report.ivPut - report.ivCall)} accent={report.ivPut - report.ivCall > 0 ? 'rose' : 'emerald'} />
                <IndTile label="Support" value={fmtNum(report.support)} accent="emerald" />
                <IndTile label="Resistance" value={fmtNum(report.resistance)} accent="rose" />
                <IndTile label="Call Chg OI" value={fmtOI(report.callChgOi)} />
                <IndTile label="Put Chg OI" value={fmtOI(report.putChgOi)} />
              </div>

              <div className="flex items-center gap-3">
                <TrendBadge trend={report.trend} score={report.trendScore} />
                <Badge variant="outline" className="text-xs">Total Call OI {fmtOI(report.totalCallOi)}</Badge>
                <Badge variant="outline" className="text-xs">Total Put OI {fmtOI(report.totalPutOi)}</Badge>
              </div>

              {/* Summary */}
              {data?.summary && (
                <Card className="p-4 bg-muted/20">
                  <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Analytics Summary</div>
                  <div className="space-y-2 text-sm">
                    {Object.entries(data.summary).map(([k, v]) => (
                      <div key={k} className="flex gap-2">
                        <span className="text-xs text-muted-foreground font-medium capitalize min-w-[90px] shrink-0 pt-0.5">{k}:</span>
                        <span className="text-sm">{v}</span>
                      </div>
                    ))}
                  </div>
                </Card>
              )}

              {/* Option chain table */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="text-sm font-semibold">Option Chain ({data?.strikes?.length ?? 0} strikes)</div>
                  {report && <ExportMenu onExport={(f) => {
                    if (f === 'pdf') { window.open(`/api/reports/${report.id}/export?format=pdf`); return }
                    window.location.href = `/api/reports/${report.id}/export?format=${f}`
                  }} />}
                </div>
                <div className="rounded-lg border overflow-hidden">
                  <div className="overflow-x-auto max-h-[420px] scroll-thin">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0 bg-muted/50 backdrop-blur">
                        <tr className="text-muted-foreground">
                          <th rowSpan={2} className="px-2 py-2 text-left font-medium border-b border-r">Strike</th>
                          <th colSpan={4} className="px-2 py-1.5 text-center font-medium border-b border-r bg-emerald-500/5">CALLS</th>
                          <th colSpan={4} className="px-2 py-1.5 text-center font-medium border-b bg-rose-500/5">PUTS</th>
                        </tr>
                        <tr className="text-muted-foreground text-[10px]">
                          <th className="px-2 py-1.5 text-right font-medium border-b border-r">LTP</th>
                          <th className="px-2 py-1.5 text-right font-medium border-b border-r">OI</th>
                          <th className="px-2 py-1.5 text-right font-medium border-b border-r">Chg OI</th>
                          <th className="px-2 py-1.5 text-right font-medium border-b border-r">IV</th>
                          <th className="px-2 py-1.5 text-right font-medium border-b border-r">LTP</th>
                          <th className="px-2 py-1.5 text-right font-medium border-b border-r">OI</th>
                          <th className="px-2 py-1.5 text-right font-medium border-b border-r">Chg OI</th>
                          <th className="px-2 py-1.5 text-right font-medium border-b">IV</th>
                        </tr>
                      </thead>
                      <tbody>
                        {isLoading ? (
                          <tr><td colSpan={9} className="px-2 py-6 text-center text-muted-foreground">Loading chain…</td></tr>
                        ) : (
                          data?.strikes?.map((s) => {
                            const isAtm = s.strike === report.atmStrike
                            const itm = s.strike < report.spotPrice
                            return (
                              <tr key={s.strike} className={cn('border-b last:border-0', isAtm && 'bg-primary/10')}>
                                <td className={cn('px-2 py-1.5 font-semibold tnum border-r', isAtm && 'text-primary')}>{s.strike}</td>
                                <td className={cn('px-2 py-1.5 text-right tnum border-r', itm && 'bg-emerald-500/5')}>{fmtNum(s.ceLtp)}</td>
                                <td className="px-2 py-1.5 text-right tnum border-r text-muted-foreground">{fmtOI(s.ceOi)}</td>
                                <td className={cn('px-2 py-1.5 text-right tnum border-r', s.ceChgOi > 0 ? 'text-emerald-500' : s.ceChgOi < 0 ? 'text-rose-500' : 'text-muted-foreground')}>{fmtSigned(s.ceChgOi, 0)}</td>
                                <td className="px-2 py-1.5 text-right tnum border-r text-muted-foreground">{fmtNum(s.ceIv, 1)}</td>
                                <td className={cn('px-2 py-1.5 text-right tnum border-r', !itm && 'bg-rose-500/5')}>{fmtNum(s.peLtp)}</td>
                                <td className="px-2 py-1.5 text-right tnum border-r text-muted-foreground">{fmtOI(s.peOi)}</td>
                                <td className={cn('px-2 py-1.5 text-right tnum border-r', s.peChgOi > 0 ? 'text-emerald-500' : s.peChgOi < 0 ? 'text-rose-500' : 'text-muted-foreground')}>{fmtSigned(s.peChgOi, 0)}</td>
                                <td className="px-2 py-1.5 text-right tnum text-muted-foreground">{fmtNum(s.peIv, 1)}</td>
                              </tr>
                            )
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
                <div className="mt-2 flex items-center gap-3 text-[11px] text-muted-foreground">
                  <span className="flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-primary/30" /> ATM strike</span>
                  <span className="flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-emerald-500/15" /> ITM calls</span>
                  <span className="flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-rose-500/15" /> ITM puts</span>
                </div>
              </div>
            </div>
          </ScrollArea>
        )}
      </SheetContent>
    </Sheet>
  )
}

function IndTile({ label, value, accent }: { label: string; value: string; accent?: 'emerald' | 'rose' | 'default' }) {
  const c = accent === 'emerald' ? 'text-emerald-500' : accent === 'rose' ? 'text-rose-500' : ''
  return (
    <div className="rounded-lg border bg-card/40 px-3 py-2">
      <div className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</div>
      <div className={cn('text-base font-semibold tnum', c)}>{value}</div>
    </div>
  )
}
