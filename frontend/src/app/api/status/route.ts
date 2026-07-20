import { NextResponse } from 'next/server'
import { db } from '@/lib/db'
import { schedulerEnabled } from '@/lib/scheduler'

export const dynamic = 'force-dynamic'

export async function GET() {
  const [profiles, reports, executions, logs, channels, lastReport] = await Promise.all([
    db.profile.count(),
    db.report.count(),
    db.execution.count(),
    db.log.count(),
    db.notificationChannel.count(),
    db.report.findFirst({ orderBy: { generatedAt: 'desc' } }),
  ])

  const running = await db.execution.count({ where: { status: 'running' } })
  const failedToday = await db.execution.count({
    where: { status: 'failed', startedAt: { gte: new Date(Date.now() - 86400000) } },
  })
  const successToday = await db.execution.count({
    where: { status: 'success', startedAt: { gte: new Date(Date.now() - 86400000) } },
  })
  const enabledProfiles = await db.profile.count({ where: { enabled: true, paused: false } })

  const upcoming = await db.profile.findMany({
    where: { enabled: true, paused: false, nextRunAt: { gt: new Date() } },
    orderBy: { nextRunAt: 'asc' },
    take: 5,
  })

  return NextResponse.json({
    counts: { profiles, reports, executions, logs, channels, running, failedToday, successToday, enabledProfiles },
    schedulerEnabled,
    lastReport: lastReport
      ? { id: lastReport.id, symbol: lastReport.symbol, generatedAt: lastReport.generatedAt, trend: lastReport.trend }
      : null,
    upcoming: upcoming.map((p) => ({ id: p.id, name: p.name, symbol: p.symbol, nextRunAt: p.nextRunAt, intervalMin: p.intervalMin })),
  })
}
