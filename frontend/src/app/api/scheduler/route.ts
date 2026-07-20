import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'
import { setSchedulerEnabled } from '@/lib/scheduler'

export const dynamic = 'force-dynamic'

export async function GET() {
  return NextResponse.json({ enabled: true })
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}))
  if (typeof body.enabled === 'boolean') {
    setSchedulerEnabled(body.enabled)
    await db.systemSetting.upsert({
      where: { id: 'scheduler.enabled' },
      update: { value: String(body.enabled) },
      create: { id: 'scheduler.enabled', value: String(body.enabled) },
    })
    return NextResponse.json({ ok: true, enabled: body.enabled })
  }
  return NextResponse.json({ error: 'enabled required' }, { status: 400 })
}
