import { NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function GET() {
  const mem = process.memoryUsage()
  const profiles = await db.profile.count()
  const reports = await db.report.count()
  const executions = await db.execution.count()
  const logs = await db.log.count()
  const running = await db.execution.count({ where: { status: 'running' } })
  const failed = await db.execution.count({ where: { status: 'failed', startedAt: { gte: new Date(Date.now() - 3600000) } } })

  // simulate CPU load 0..100 based on running jobs
  const cpu = Math.min(100, running * 12 + Math.round(Math.random() * 8))
  const memPct = Math.round((mem.heapUsed / mem.heapTotal) * 100)

  const now = new Date()
  const inHours = now.getHours()
  const marketOpen = inHours >= 9 && inHours < 16
  const settings = await db.systemSetting.findMany()
  const cfg = Object.fromEntries(settings.map((s) => [s.id, s.value]))

  return NextResponse.json({
    cpu,
    memPct,
    heapUsedMb: Math.round(mem.heapUsed / 1048576),
    heapTotalMb: Math.round(mem.heapTotal / 1048576),
    uptimeSec: Math.round(process.uptime()),
    db: { profiles, reports, executions, logs },
    running,
    failedLastHour: failed,
    marketOpen,
    schedule: { start: cfg['market.hours.start'] ?? '09:15', end: cfg['market.hours.end'] ?? '15:30' },
    portal: { url: cfg['portal.url'] ?? '', timeout: cfg['portal.timeout'] ?? '45000' },
  })
}
