'use client'

import * as React from 'react'
import { cn } from '@/lib/utils'

export function LiveDot({ className }: { className?: string }) {
  return (
    <span className="relative inline-flex h-2 w-2">
      <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60 live-dot" />
      <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
    </span>
  )
}

export function SectionHeader({
  title,
  description,
  icon,
  action,
}: {
  title: string
  description?: string
  icon?: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-4 mb-4">
      <div className="flex items-start gap-3 min-w-0">
        {icon && <div className="mt-0.5 text-primary shrink-0">{icon}</div>}
        <div className="min-w-0">
          <h2 className="text-lg font-semibold tracking-tight truncate">{title}</h2>
          {description && <p className="text-sm text-muted-foreground mt-0.5">{description}</p>}
        </div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

export function StatCard({
  label,
  value,
  sub,
  icon,
  trend,
  accent,
}: {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  icon?: React.ReactNode
  trend?: 'up' | 'down' | 'neutral'
  accent?: 'primary' | 'emerald' | 'rose' | 'amber' | 'default'
}) {
  const accentMap: Record<string, string> = {
    primary: 'text-primary',
    emerald: 'text-emerald-500',
    rose: 'text-rose-500',
    amber: 'text-amber-500',
    default: 'text-foreground',
  }
  const trendColor = trend === 'up' ? 'text-emerald-500' : trend === 'down' ? 'text-rose-500' : 'text-muted-foreground'
  return (
    <div className="rounded-xl border bg-card p-4 lg:p-5 relative overflow-hidden group hover:border-primary/40 transition-colors">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">{label}</span>
        {icon && <span className={cn('opacity-70', accentMap[accent ?? 'default'])}>{icon}</span>}
      </div>
      <div className={cn('text-2xl lg:text-3xl font-semibold tnum', accentMap[accent ?? 'default'])}>{value}</div>
      {sub && <div className={cn('text-xs mt-1.5 tnum', trendColor)}>{sub}</div>}
    </div>
  )
}

export function TrendBadge({ trend, score }: { trend: string; score?: number }) {
  const map: Record<string, { c: string; bg: string; label: string }> = {
    bullish: { c: 'text-emerald-500', bg: 'bg-emerald-500/10 border-emerald-500/30', label: 'Bullish' },
    bearish: { c: 'text-rose-500', bg: 'bg-rose-500/10 border-rose-500/30', label: 'Bearish' },
    neutral: { c: 'text-amber-500', bg: 'bg-amber-500/10 border-amber-500/30', label: 'Neutral' },
  }
  const m = map[trend] ?? map.neutral
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium', m.bg, m.c)}>
      <span className={cn('h-1.5 w-1.5 rounded-full', m.c.replace('text-', 'bg-'))} />
      {m.label}
      {score != null && <span className="tnum opacity-80">({score > 0 ? '+' : ''}{score})</span>}
    </span>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { c: string; bg: string; label: string }> = {
    success: { c: 'text-emerald-500', bg: 'bg-emerald-500/10', label: 'Success' },
    running: { c: 'text-sky-400', bg: 'bg-sky-400/10', label: 'Running' },
    failed: { c: 'text-rose-500', bg: 'bg-rose-500/10', label: 'Failed' },
    cancelled: { c: 'text-amber-500', bg: 'bg-amber-500/10', label: 'Cancelled' },
    sent: { c: 'text-emerald-500', bg: 'bg-emerald-500/10', label: 'Sent' },
    queued: { c: 'text-amber-500', bg: 'bg-amber-500/10', label: 'Queued' },
    captured: { c: 'text-emerald-500', bg: 'bg-emerald-500/10', label: 'Captured' },
  }
  const m = map[status] ?? { c: 'text-muted-foreground', bg: 'bg-muted', label: status }
  return (
    <span className={cn('inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium capitalize', m.bg, m.c)}>
      {status === 'running' && <LiveDot className="mr-1" />}
      {m.label}
    </span>
  )
}

export function MiniBar({ value, max, color = 'bg-primary' }: { value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
      <div className={cn('h-full rounded-full transition-all', color)} style={{ width: pct + '%' }} />
    </div>
  )
}

export function EmptyState({ icon, title, description, action }: { icon?: React.ReactNode; title: string; description?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      {icon && <div className="text-muted-foreground/40 mb-3">{icon}</div>}
      <p className="text-sm font-medium">{title}</p>
      {description && <p className="text-xs text-muted-foreground mt-1 max-w-sm">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
