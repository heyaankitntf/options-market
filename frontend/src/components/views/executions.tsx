'use client'

import * as React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, RotateCcw, Filter, CheckCircle2, XCircle, Loader2, Clock } from 'lucide-react'
import { api, type Execution } from '@/lib/api'
import { fmtDateTime, relTime } from '@/lib/format'
import { SectionHeader, StatusBadge, EmptyState } from '@/components/ui/primitives'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'

const STAGES = ['login', 'navigate', 'select', 'export', 'process', 'notify', 'done']

export function ExecutionsView() {
  const qc = useQueryClient()
  const { toast } = useToast()
  const [status, setStatus] = React.useState('ALL')
  const [profileId, setProfileId] = React.useState('ALL')

  const { data, isLoading } = useQuery({
    queryKey: ['executions', status, profileId],
    queryFn: () => {
      const params = new URLSearchParams({ limit: '100' })
      if (status !== 'ALL') params.set('status', status)
      if (profileId !== 'ALL') params.set('profileId', profileId)
      return api<Execution[]>(`/api/executions?${params}`)
    },
    refetchInterval: 6000,
  })

  const { data: profiles } = useQuery({ queryKey: ['profiles-mini'], queryFn: () => api<{ id: string; name: string; symbol: string }[]>('/api/profiles') })

  const rerun = async (id: string) => {
    try {
      await api(`/api/executions/${id}/rerun`, { method: 'POST' })
      toast({ title: 'Rerun triggered' })
      qc.invalidateQueries({ queryKey: ['executions'] })
    } catch (e) {
      toast({ title: 'Failed', description: String(e), variant: 'destructive' })
    }
  }

  const counts = React.useMemo(() => {
    const c = { success: 0, failed: 0, running: 0, cancelled: 0 }
    for (const e of data ?? []) c[e.status as keyof typeof c] = (c[e.status as keyof typeof c] ?? 0) + 1
    return c
  }, [data])

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MiniStat label="Success" value={counts.success} icon={<CheckCircle2 className="h-4 w-4" />} color="text-emerald-500" />
        <MiniStat label="Failed" value={counts.failed} icon={<XCircle className="h-4 w-4" />} color="text-rose-500" />
        <MiniStat label="Running" value={counts.running} icon={<Loader2 className="h-4 w-4 animate-spin" />} color="text-sky-400" />
        <MiniStat label="Cancelled" value={counts.cancelled} icon={<Clock className="h-4 w-4" />} color="text-amber-500" />
      </div>

      <Card className="p-4">
        <div className="flex items-center gap-2 flex-wrap">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-[140px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              {['ALL', 'success', 'failed', 'running', 'cancelled'].map((s) => <SelectItem key={s} value={s} className="capitalize">{s === 'ALL' ? 'All Status' : s}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={profileId} onValueChange={setProfileId}>
            <SelectTrigger className="w-[200px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Profiles</SelectItem>
              {profiles?.map((p) => <SelectItem key={p.id} value={p.id}>{p.symbol} · {p.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </Card>

      <Card className="p-0 overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Activity className="h-4 w-4 text-primary" /> Execution History
            <Badge variant="secondary">{data?.length ?? 0}</Badge>
          </div>
        </div>
        <div className="overflow-x-auto scroll-thin">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/30 text-xs text-muted-foreground">
                <th className="px-3 py-2.5 text-left font-medium">Status</th>
                <th className="px-3 py-2.5 text-left font-medium">Profile</th>
                <th className="px-3 py-2.5 text-left font-medium">Stage</th>
                <th className="px-3 py-2.5 text-left font-medium">Trigger</th>
                <th className="px-3 py-2.5 text-right font-medium">Duration</th>
                <th className="px-3 py-2.5 text-left font-medium">Started</th>
                <th className="px-3 py-2.5 text-left font-medium">Error</th>
                <th className="px-3 py-2.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={8} className="px-3 py-8 text-center text-muted-foreground">Loading…</td></tr>
              ) : data?.length === 0 ? (
                <tr><td colSpan={8} className="px-3 py-8"><EmptyState icon={<Activity className="h-8 w-8" />} title="No executions" description="Run a profile to see executions here." /></td></tr>
              ) : (
                data.map((e) => (
                  <tr key={e.id} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
                    <td className="px-3 py-2.5"><StatusBadge status={e.status} /></td>
                    <td className="px-3 py-2.5">
                      <div className="font-medium">{e.profile?.symbol}</div>
                      <div className="text-[11px] text-muted-foreground truncate max-w-[180px]">{e.profile?.name}</div>
                    </td>
                    <td className="px-3 py-2.5">
                      <StageProgress stage={e.stage} status={e.status} />
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge variant="outline" className="text-[11px] capitalize">{e.triggeredBy}</Badge>
                    </td>
                    <td className="px-3 py-2.5 text-right tnum text-muted-foreground">
                      {e.durationMs ? `${(e.durationMs / 1000).toFixed(1)}s` : '—'}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-muted-foreground">
                      <div>{relTime(e.startedAt)}</div>
                      <div className="text-[10px]">{fmtDateTime(e.startedAt)}</div>
                    </td>
                    <td className="px-3 py-2.5 max-w-[220px]">
                      {e.error ? (
                        <TooltipProvider delayDuration={150}>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span className="text-xs text-rose-400 truncate block cursor-help">{e.error}</span>
                            </TooltipTrigger>
                            <TooltipContent className="max-w-xs">{e.error}</TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      ) : <span className="text-muted-foreground/40 text-xs">—</span>}
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => rerun(e.id)}>
                              <RotateCcw className="h-3.5 w-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>Rerun pipeline</TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

function StageProgress({ stage, status }: { stage: string; status: string }) {
  const idx = STAGES.indexOf(stage)
  return (
    <div className="flex items-center gap-1">
      {STAGES.slice(0, -1).map((s, i) => (
        <TooltipProvider key={s} delayDuration={150}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className={cn(
                'h-1.5 w-4 rounded-full transition-colors',
                status === 'failed' && i === idx ? 'bg-rose-500'
                : i < idx ? 'bg-emerald-500'
                : i === idx ? 'bg-sky-400'
                : 'bg-muted',
              )} />
            </TooltipTrigger>
            <TooltipContent>{s}</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ))}
      <span className="ml-1.5 text-[11px] text-muted-foreground capitalize">{stage}</span>
    </div>
  )
}

function MiniStat({ label, value, icon, color }: { label: string; value: number; icon: React.ReactNode; color: string }) {
  return (
    <Card className="p-4 flex items-center gap-3">
      <div className={cn('h-9 w-9 rounded-lg bg-muted/40 flex items-center justify-center', color)}>{icon}</div>
      <div>
        <div className="text-xl font-semibold tnum">{value}</div>
        <div className="text-xs text-muted-foreground">{label}</div>
      </div>
    </Card>
  )
}
