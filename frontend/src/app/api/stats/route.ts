import { NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function GET() {
  const total = await db.execution.count()
  const success = await db.execution.count({ where: { status: 'success' } })
  const failed = await db.execution.count({ where: { status: 'failed' } })
  const running = await db.execution.count({ where: { status: 'running' } })

  // Success rate over last 24h
  const since = new Date(Date.now() - 86400000)
  const last24 = await db.execution.findMany({
    where: { startedAt: { gte: since } },
    orderBy: { startedAt: 'asc' },
  })
  const buckets = bucketize(last24, 60)
  const successRate = total > 0 ? Math.round((success / total) * 100) : 0

  // Per-profile stats
  const profiles = await db.profile.findMany({
    select: { id: true, name: true, symbol: true, runCount: true, successCount: true, failCount: true, avgDurationMs: true, lastStatus: true },
  })

  // Avg duration
  const avgDuration = await db.execution.aggregate({ _avg: { durationMs: true } })

  return NextResponse.json({
    totals: { total, success, failed, running, successRate },
    avgDurationMs: Math.round(avgDuration._avg.durationMs ?? 0),
    timeline: buckets,
    profiles: profiles.map((p) => ({
      ...p,
      successRate: p.runCount > 0 ? Math.round((p.successCount / p.runCount) * 100) : 0,
    })),
  })
}

function bucketize(execs: { startedAt: Date; status: string; durationMs: number }[], bucketMin: number) {
  const map = new Map<string, { time: string; success: number; failed: number; running: number; avgMs: number; n: number }>()
  for (const e of execs) {
    const d = new Date(e.startedAt)
    d.setMinutes(Math.floor(d.getMinutes() / bucketMin) * bucketMin, 0, 0)
    const key = d.toISOString()
    const b = map.get(key) ?? { time: key, success: 0, failed: 0, running: 0, avgMs: 0, n: 0 }
    if (e.status === 'success') b.success++
    else if (e.status === 'failed') b.failed++
    else if (e.status === 'running') b.running++
    b.avgMs += e.durationMs
    b.n++
    map.set(key, b)
  }
  return Array.from(map.values()).map((b) => ({ ...b, avgMs: b.n ? Math.round(b.avgMs / b.n) : 0 }))
}
