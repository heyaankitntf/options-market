'use client'

import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ScrollText, Terminal, Info, AlertTriangle, AlertOctagon, Bug, Globe,
  Cog, Brain, Bell, RefreshCw, Trash2,
} from 'lucide-react'
import { api, type LogEntry } from '@/lib/api'
import { fmtTime, fmtDateTime } from '@/lib/format'
import { EmptyState, LiveDot } from '@/components/ui/primitives'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'

const LEVELS = [
  { id: 'ALL', label: 'All Levels' },
  { id: 'info', label: 'Info' },
  { id: 'warn', label: 'Warnings' },
  { id: 'error', label: 'Errors' },
  { id: 'debug', label: 'Debug' },
  { id: 'browser', label: 'Browser' },
]
const SOURCES = ['ALL', 'system', 'browser', 'engine', 'scheduler', 'notify']

const levelMeta: Record<string, { icon: React.ReactNode; color: string; bg: string }> = {
  info: { icon: <Info className="h-3.5 w-3.5" />, color: 'text-sky-400', bg: 'bg-sky-400/10' },
  warn: { icon: <AlertTriangle className="h-3.5 w-3.5" />, color: 'text-amber-400', bg: 'bg-amber-400/10' },
  error: { icon: <AlertOctagon className="h-3.5 w-3.5" />, color: 'text-rose-400', bg: 'bg-rose-400/10' },
  debug: { icon: <Bug className="h-3.5 w-3.5" />, color: 'text-muted-foreground', bg: 'bg-muted' },
  browser: { icon: <Globe className="h-3.5 w-3.5" />, color: 'text-violet-400', bg: 'bg-violet-400/10' },
}

const sourceMeta: Record<string, React.ReactNode> = {
  system: <Cog className="h-3 w-3" />,
  browser: <Globe className="h-3 w-3" />,
  engine: <Brain className="h-3 w-3" />,
  scheduler: <RefreshCw className="h-3 w-3" />,
  notify: <Bell className="h-3 w-3" />,
}

export function LogsView() {
  const [level, setLevel] = React.useState('ALL')
  const [source, setSource] = React.useState('ALL')
  const [autoScroll, setAutoScroll] = React.useState(true)
  const endRef = React.useRef<HTMLDivElement>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['logs', level, source],
    queryFn: () => {
      const params = new URLSearchParams({ limit: '300' })
      if (level !== 'ALL') params.set('level', level)
      if (source !== 'ALL') params.set('source', source)
      return api<LogEntry[]>(`/api/logs?${params}`)
    },
    refetchInterval: 4000,
  })

  React.useEffect(() => {
    if (autoScroll && endRef.current) endRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [data, autoScroll])

  const counts = React.useMemo(() => {
    const c = { info: 0, warn: 0, error: 0, debug: 0, browser: 0 }
    for (const l of data ?? []) c[l.level as keyof typeof c] = (c[l.level as keyof typeof c] ?? 0) + 1
    return c
  }, [data])

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <LevelStat label="Info" count={counts.info} color="text-sky-400" bg="bg-sky-400/10" icon={<Info className="h-4 w-4" />} />
        <LevelStat label="Warnings" count={counts.warn} color="text-amber-400" bg="bg-amber-400/10" icon={<AlertTriangle className="h-4 w-4" />} />
        <LevelStat label="Errors" count={counts.error} color="text-rose-400" bg="bg-rose-400/10" icon={<AlertOctagon className="h-4 w-4" />} />
        <LevelStat label="Debug" count={counts.debug} color="text-muted-foreground" bg="bg-muted" icon={<Bug className="h-4 w-4" />} />
        <LevelStat label="Browser" count={counts.browser} color="text-violet-400" bg="bg-violet-400/10" icon={<Globe className="h-4 w-4" />} />
      </div>

      <Card className="p-4">
        <div className="flex items-center gap-2 flex-wrap">
          <Terminal className="h-4 w-4 text-muted-foreground" />
          <Select value={level} onValueChange={setLevel}>
            <SelectTrigger className="w-[140px]"><SelectValue /></SelectTrigger>
            <SelectContent>{LEVELS.map((l) => <SelectItem key={l.id} value={l.id}>{l.label}</SelectItem>)}</SelectContent>
          </Select>
          <Select value={source} onValueChange={setSource}>
            <SelectTrigger className="w-[140px]"><SelectValue /></SelectTrigger>
            <SelectContent>{SOURCES.map((s) => <SelectItem key={s} value={s} className="capitalize">{s === 'ALL' ? 'All Sources' : s}</SelectItem>)}</SelectContent>
          </Select>
          <label className="ml-auto flex items-center gap-2 text-xs cursor-pointer">
            <LiveDot /> <span className="text-muted-foreground">Live stream</span>
          </label>
        </div>
      </Card>

      <Card className="p-0 overflow-hidden">
        <div className="px-4 py-2.5 border-b flex items-center justify-between bg-muted/20">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ScrollText className="h-4 w-4 text-primary" /> Processing & Browser Logs
            <Badge variant="secondary">{data?.length ?? 0}</Badge>
          </div>
          <span className="text-xs text-muted-foreground font-mono">tail -f /var/log/optflow</span>
        </div>
        <div className="max-h-[600px] overflow-y-auto scroll-thin font-mono text-xs">
          {isLoading ? (
            <div className="px-4 py-8 text-center text-muted-foreground">Loading logs…</div>
          ) : !data?.length ? (
            <EmptyState icon={<ScrollText className="h-8 w-8" />} title="No logs" description="Logs appear as the automation runs." />
          ) : (
            <div className="divide-y divide-border/50">
              {data.map((l) => {
                const m = levelMeta[l.level] ?? levelMeta.info
                return (
                  <div key={l.id} className="px-4 py-2 flex items-start gap-3 hover:bg-muted/20 transition-colors group">
                    <span className="text-muted-foreground/60 tnum shrink-0 mt-0.5 hidden sm:block">{fmtTime(l.createdAt)}</span>
                    <span className={cn('inline-flex items-center justify-center h-5 w-5 rounded shrink-0 mt-0.5', m.bg, m.color)}>{m.icon}</span>
                    <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground uppercase shrink-0 mt-0.5 w-20">
                      {sourceMeta[l.source] ?? <Cog className="h-3 w-3" />} {l.source}
                    </span>
                    <span className="flex-1 break-words leading-relaxed">
                      <span className="text-foreground">{l.message}</span>
                      {l.meta && (
                        <span className="text-muted-foreground/60 ml-2">{l.meta}</span>
                      )}
                      {l.execution?.profile && (
                        <span className="ml-2 text-muted-foreground/50">[{l.execution.profile.symbol} · {l.execution.profile.name}]</span>
                      )}
                    </span>
                  </div>
                )
              })}
              <div ref={endRef} />
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}

function LevelStat({ label, count, color, bg, icon }: { label: string; count: number; color: string; bg: string; icon: React.ReactNode }) {
  return (
    <Card className="p-3 flex items-center gap-2.5">
      <div className={cn('h-8 w-8 rounded-md flex items-center justify-center', bg, color)}>{icon}</div>
      <div>
        <div className="text-lg font-semibold tnum">{count}</div>
        <div className="text-[11px] text-muted-foreground">{label}</div>
      </div>
    </Card>
  )
}
