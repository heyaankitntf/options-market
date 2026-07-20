'use client'

import * as React from 'react'
import { useTheme } from 'next-themes'
import {
  LayoutDashboard, FileBarChart, Workflow, ScrollText, Settings,
  Bell, Activity, Sun, Moon, Play, Pause, RefreshCw, Zap, TrendingUp,
  Menu, X, ShieldCheck, Clock, Database, LineChart as LineChartIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { api, type StatusResponse, type HealthResponse } from '@/lib/api'
import { LiveDot } from '@/components/ui/primitives'
import { useToast } from '@/hooks/use-toast'
import { DashboardView } from '@/components/views/dashboard'
import { ReportsView } from '@/components/views/reports'
import { ExecutionsView } from '@/components/views/executions'
import { ProfilesView } from '@/components/views/profiles'
import { LogsView } from '@/components/views/logs'
import { NotificationsView } from '@/components/views/notifications'
import { AdminView } from '@/components/views/admin'
import { AnalyticsView } from '@/components/views/analytics'
import { MarketTicker } from '@/components/market-ticker'

type ViewId = 'dashboard' | 'analytics' | 'reports' | 'executions' | 'profiles' | 'logs' | 'notifications' | 'admin'

const NAV: { id: ViewId; label: string; icon: React.ReactNode; group: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard className="h-4 w-4" />, group: 'Monitor' },
  { id: 'analytics', label: 'Deep Analytics', icon: <LineChartIcon className="h-4 w-4" />, group: 'Monitor' },
  { id: 'reports', label: 'Reports', icon: <FileBarChart className="h-4 w-4" />, group: 'Monitor' },
  { id: 'executions', label: 'Executions', icon: <Activity className="h-4 w-4" />, group: 'Monitor' },
  { id: 'logs', label: 'Processing Logs', icon: <ScrollText className="h-4 w-4" />, group: 'Monitor' },
  { id: 'profiles', label: 'Automation Profiles', icon: <Workflow className="h-4 w-4" />, group: 'Configure' },
  { id: 'notifications', label: 'Notifications', icon: <Bell className="h-4 w-4" />, group: 'Configure' },
  { id: 'admin', label: 'Administration', icon: <Settings className="h-4 w-4" />, group: 'Configure' },
]

export default function Home() {
  const [view, setView] = React.useState<ViewId>('dashboard')
  const [mobileOpen, setMobileOpen] = React.useState(false)
  const [status, setStatus] = React.useState<StatusResponse | null>(null)
  const [health, setHealth] = React.useState<HealthResponse | null>(null)
  const [schedEnabled, setSchedEnabled] = React.useState(true)
  const [toggling, setToggling] = React.useState(false)
  const { toast } = useToast()

  const refresh = React.useCallback(async () => {
    try {
      const [s, h] = await Promise.all([api<StatusResponse>('/api/status'), api<HealthResponse>('/api/health')])
      setStatus(s)
      setHealth(h)
      setSchedEnabled(s.schedulerEnabled)
    } catch (e) {
      console.error(e)
    }
  }, [])

  React.useEffect(() => {
    refresh()
    const i = setInterval(refresh, 8000)
    return () => clearInterval(i)
  }, [refresh])

  const toggleScheduler = async () => {
    setToggling(true)
    try {
      await api('/api/scheduler', { method: 'POST', body: JSON.stringify({ enabled: !schedEnabled }) })
      setSchedEnabled(!schedEnabled)
      toast({ title: !schedEnabled ? 'Automation enabled' : 'Automation paused' })
      refresh()
    } catch (e) {
      toast({ title: 'Failed', description: e instanceof Error ? e.message : String(e), variant: 'destructive' })
    } finally {
      setToggling(false)
    }
  }

  const runningCount = status?.counts.running ?? 0

  return (
    <div className="min-h-screen flex flex-col bg-background">
      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <aside
          className={cn(
            'w-64 shrink-0 border-r bg-sidebar flex flex-col transition-transform lg:translate-x-0 fixed lg:static inset-y-0 left-0 z-40',
            mobileOpen ? 'translate-x-0' : '-translate-x-full',
          )}
        >
          <div className="h-16 flex items-center gap-2.5 px-5 border-b">
            <div className="h-9 w-9 rounded-lg bg-primary/15 border border-primary/30 flex items-center justify-center">
              <TrendingUp className="h-5 w-5 text-primary" />
            </div>
            <div className="leading-tight">
              <div className="font-semibold text-sm tracking-tight">OptFlow</div>
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Options Automation</div>
            </div>
            <button className="ml-auto lg:hidden text-muted-foreground" onClick={() => setMobileOpen(false)}>
              <X className="h-5 w-5" />
            </button>
          </div>

          <nav className="flex-1 overflow-y-auto scroll-thin py-3 px-3">
            {['Monitor', 'Configure'].map((group) => (
              <div key={group} className="mb-4">
                <div className="px-3 mb-1.5 text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wider">{group}</div>
                <div className="space-y-0.5">
                  {NAV.filter((n) => n.group === group).map((n) => (
                    <button
                      key={n.id}
                      onClick={() => { setView(n.id); setMobileOpen(false) }}
                      className={cn(
                        'w-full flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                        view === n.id
                          ? 'bg-primary/12 text-primary'
                          : 'text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                      )}
                    >
                      {n.icon}
                      {n.label}
                      {n.id === 'executions' && runningCount > 0 && (
                        <Badge variant="secondary" className="ml-auto h-5 px-1.5 text-[10px] bg-sky-500/15 text-sky-400">{runningCount}</Badge>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </nav>

          <div className="border-t p-3 space-y-2">
            <div className="rounded-lg border bg-card/50 p-3">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium flex items-center gap-1.5">
                  <Zap className="h-3.5 w-3.5 text-primary" /> Scheduler
                </span>
                <Switch checked={schedEnabled} onCheckedChange={toggleScheduler} disabled={toggling} />
              </div>
              <div className="text-[11px] text-muted-foreground flex items-center gap-1.5">
                {schedEnabled ? <LiveDot /> : <Pause className="h-3 w-3 text-amber-500" />}
                {schedEnabled ? 'Running · tick 30s' : 'Paused'}
              </div>
            </div>
            <div className="flex items-center gap-2 px-2 text-[11px] text-muted-foreground">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" />
              <span>v1.0 · icharts portal</span>
            </div>
          </div>
        </aside>

        {mobileOpen && <div className="fixed inset-0 bg-black/50 z-30 lg:hidden" onClick={() => setMobileOpen(false)} />}

        {/* Main */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Top bar */}
          <header className="h-16 border-b bg-card/40 backdrop-blur-sm flex items-center gap-3 px-4 lg:px-6 sticky top-0 z-20">
            <button className="lg:hidden text-muted-foreground" onClick={() => setMobileOpen(true)}>
              <Menu className="h-5 w-5" />
            </button>
            <div className="min-w-0">
              <h1 className="font-semibold text-base lg:text-lg tracking-tight capitalize truncate">
                {NAV.find((n) => n.id === view)?.label}
              </h1>
              <p className="text-[11px] text-muted-foreground hidden sm:block">
                {health?.marketOpen ? 'Market open' : 'Market closed'} · {health ? `${health.schedule.start}–${health.schedule.end} IST` : ''}
              </p>
            </div>

            <div className="ml-auto flex items-center gap-2 lg:gap-3">
              {health && (
                <div className="hidden md:flex items-center gap-3 text-xs">
                  <HeaderStat icon={<Activity className="h-3.5 w-3.5" />} label="CPU" value={`${health.cpu}%`} warn={health.cpu > 80} />
                  <HeaderStat icon={<Database className="h-3.5 w-3.5" />} label="Heap" value={`${health.heapUsedMb}MB`} />
                  <HeaderStat icon={<Clock className="h-3.5 w-3.5" />} label="Uptime" value={fmtUptime(health.uptimeSec)} />
                </div>
              )}
              {runningCount > 0 && (
                <Badge variant="secondary" className="bg-sky-500/15 text-sky-400 gap-1.5">
                  <LiveDot /> {runningCount} running
                </Badge>
              )}
              <Button size="sm" variant="outline" onClick={refresh} className="gap-1.5">
                <RefreshCw className="h-3.5 w-3.5" /> <span className="hidden sm:inline">Refresh</span>
              </Button>
              <ThemeToggle />
            </div>
          </header>

          {/* Market ticker — sticky below header */}
          <MarketTicker onSelectSymbol={() => setView('analytics')} />

          {/* Content */}
          <main className="flex-1 p-4 lg:p-6 overflow-x-hidden">
            {view === 'dashboard' && <DashboardView status={status} health={health} />}
            {view === 'analytics' && <AnalyticsView />}
            {view === 'reports' && <ReportsView />}
            {view === 'executions' && <ExecutionsView />}
            {view === 'profiles' && <ProfilesView />}
            {view === 'logs' && <LogsView />}
            {view === 'notifications' && <NotificationsView />}
            {view === 'admin' && <AdminView />}
          </main>

          {/* Sticky footer */}
          <footer className="mt-auto border-t bg-card/40 px-4 lg:px-6 py-3 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-muted-foreground">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1.5">
                <Play className="h-3 w-3 text-emerald-500" /> OptFlow Engine
              </span>
              <span className="hidden sm:inline">·</span>
              <span className="hidden sm:flex items-center gap-1.5">
                <Database className="h-3 w-3" />
                {status ? `${status.counts.reports} reports · ${status.counts.executions} runs` : ''}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <span>© {new Date().getFullYear()} OptFlow · Automated Options Analytics</span>
            </div>
          </footer>
        </div>
      </div>
    </div>
  )
}

function HeaderStat({ icon, label, value, warn }: { icon: React.ReactNode; label: string; value: string; warn?: boolean }) {
  return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-muted/50">
      <span className={cn('text-muted-foreground', warn && 'text-amber-500')}>{icon}</span>
      <span className="text-muted-foreground">{label}</span>
      <span className={cn('font-medium tnum', warn && 'text-amber-500')}>{value}</span>
    </div>
  )
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted] = React.useState(false)
  React.useEffect(() => setMounted(true), [])
  if (!mounted) return <div className="h-8 w-8" />
  return (
    <Button size="icon" variant="ghost" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
      {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  )
}

function fmtUptime(s: number): string {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}
